
#!/bin/bash

set -euo pipefail
umask 077

export LC_ALL=C

# ========================================
# Configuration
# ========================================

BASE_DIR="$HOME"
TRAVEL_ROOT="/opt/travel-app"
TRAVEL_MODE=""
TRAVEL_RELEASE=""
BACKUP_ROOT="$BASE_DIR/backups/snapshots"

TIMESTAMP=$(date -u +%Y%m%d-%H%M%S)
BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"
TEMP_DIR=""

# Backup retention settings
RETENTION_DAYS=30
MIN_BACKUPS=7
INCOMPLETE_RETENTION_DAYS=7

# Minimum available disk space (MiB)
MIN_FREE_MB=2048

# Preview expired backups without deleting
DRY_RUN=true

# Backup lock
LOCK_FILE="$BACKUP_ROOT/.backup.lock"
LIFECYCLE_LOCK="$TRAVEL_ROOT/.lifecycle.lock"

DATABASES=(
    "travel_db"
    "link_db"
)

PROJECTS=(
    "google-map-searcher"
    "link_manager"
)

# ========================================
# Utility Functions
# ========================================

section() {
    printf "\n[%s]\n" "$1"
}

cleanup() {
    if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
        echo "Backup incomplete: $TEMP_DIR" >&2
    fi
}

trap cleanup EXIT

# ========================================
# Backup Lock
# ========================================

acquire_lock() {
    mkdir -p "$BACKUP_ROOT"
    chmod 700 "$BACKUP_ROOT"

    exec 9>"$LOCK_FILE"

    if ! flock -n 9; then
        echo "Another backup is already running." >&2
        exit 1
    fi

    echo "Backup lock acquired"
}

acquire_lifecycle_lock() {
    local path mode owner links lock_id fd_id group account gid acl entry
    for path in / /opt "$TRAVEL_ROOT"; do
        if [[ -L "$path" || ! -d "$path" ]]; then
            echo "Unsafe lifecycle lock ancestor" >&2; exit 1
        fi
        read -r owner mode < <(/usr/bin/stat -c '%u %a' -- "$path")
        if [[ "$owner" != 0 ]] || (( (8#$mode & 0022) != 0 )); then
            echo "Unsafe lifecycle lock ancestor permissions" >&2; exit 1
        fi
    done
    if [[ -L "$LIFECYCLE_LOCK" || ! -f "$LIFECYCLE_LOCK" ]]; then
        echo "Lifecycle lock is missing or unsafe" >&2; exit 1
    fi
    read -r owner mode links group < <(/usr/bin/stat -c '%u %a %h %g' -- "$LIFECYCLE_LOCK")
    if [[ "$owner" != 0 || "$mode" != 640 || "$links" != 1 ]]; then
        echo "Unsafe lifecycle lock permissions" >&2; exit 1
    fi
    if [[ ! -x /usr/bin/getfacl ]] || ! acl=$(/usr/bin/getfacl -cpn -- "$LIFECYCLE_LOCK"); then
        echo "Cannot verify lifecycle lock ACL" >&2; exit 1
    fi
    while IFS= read -r entry; do
        case "$entry" in
            user:[0-9]*:*|group:[0-9]*:*) echo "Named lifecycle lock ACL is not permitted" >&2; exit 1 ;;
        esac
    done <<< "$acl"
    for account in travel-deploy travel-build travel-app; do
        if ! /usr/bin/id -G "$account" >/dev/null; then
            echo "Cannot verify lifecycle lock account isolation" >&2; exit 1
        fi
        for gid in $(/usr/bin/id -G "$account"); do
            if [[ "$gid" == "$group" ]]; then
                echo "Lifecycle lock group is shared with a service account" >&2; exit 1
            fi
        done
    done
    lock_id=$(/usr/bin/stat -c '%d:%i' -- "$LIFECYCLE_LOCK")
    if ! { exec 8<"$LIFECYCLE_LOCK"; }; then
        echo "Cannot open lifecycle lock" >&2; exit 1
    fi
    fd_id=$(/usr/bin/stat -Lc '%d:%i' -- "/proc/$$/fd/8")
    if [[ "$lock_id" != "$fd_id" ]] || ! /usr/bin/flock -x -w 30 8; then
        echo "Lifecycle lock changed or timed out" >&2; exit 1
    fi
    if [[ "$lock_id" != "$(/usr/bin/stat -c '%d:%i' -- "$LIFECYCLE_LOCK")" ]]; then
        echo "Lifecycle lock changed while waiting" >&2; exit 1
    fi
    echo "Lifecycle lock acquired"
}

# ========================================
# Disk Space Check
# ========================================

check_disk_space() {
    section "Disk Space Check"

    local available_mb

    available_mb=$(df -Pm "$BACKUP_ROOT" |
        awk 'NR == 2 {print $4}')

    if ! [[ "$available_mb" =~ ^[0-9]+$ ]]; then
        echo "Unable to check disk space" >&2
        exit 1
    fi

    echo "Available space: ${available_mb} MiB"
    echo "Required space: ${MIN_FREE_MB} MiB"

    if (( available_mb < MIN_FREE_MB )); then
        echo "Insufficient disk space" >&2
        exit 1
    fi

    echo "Disk space check: PASS"
}

# ========================================
# Prepare Backup
# ========================================

prepare_backup() {
    section "Prepare Backup"

    TEMP_DIR=$(mktemp -d \
        "$BACKUP_ROOT/.incomplete-$TIMESTAMP-XXXXXX")

    mkdir -p "$TEMP_DIR"/{database,environment,config,firewall,data,metadata,scripts}

    echo "Backup time: $TIMESTAMP UTC"
    echo "Temporary directory: $TEMP_DIR"
}

# ========================================
# Database Backup
# ========================================

backup_databases() {
    section "Database Backup"

    local db
    local backup_file

    for db in "${DATABASES[@]}"; do

        backup_file="$TEMP_DIR/database/$db.dump"

        echo "Backing up: $db"

        (
            cd /tmp
            sudo -n -u postgres /usr/bin/pg_dump -Fc "$db"
        ) > "$backup_file"

        test -s "$backup_file"

        pg_restore -l "$backup_file" > /dev/null

        echo "$db: PASS"

    done

    (
        cd /tmp
        sudo -n -u postgres /usr/bin/pg_dumpall --globals-only
    ) > "$TEMP_DIR/database/globals.sql"

    test -s "$TEMP_DIR/database/globals.sql"

    echo "PostgreSQL globals: PASS"
}

# ========================================
# Environment Backup
# ========================================

detect_travel_layout() {
    local workdir

    workdir=$(systemctl show travel.service \
        -p WorkingDirectory --value)

    case "$workdir" in
        /home/ubuntu/travel_app)
            TRAVEL_MODE="legacy"
            TRAVEL_RELEASE="$BASE_DIR/travel_app"
            ;;

        /opt/travel-app/current)
            TRAVEL_MODE="release"
            TRAVEL_RELEASE=$(readlink -f "$TRAVEL_ROOT/current")

            if ! [[ "$TRAVEL_RELEASE" =~ ^/opt/travel-app/releases/[0-9a-f]{40}$ ]]; then
                echo "Invalid travel release path" >&2
                exit 1
            fi

            test -f "$TRAVEL_RELEASE/REVISION"
            test "$(cat "$TRAVEL_RELEASE/REVISION")" = "${TRAVEL_RELEASE##*/}"
            if ! sudo -n /usr/local/sbin/travel-backup-guard verify-state; then
                echo "Travel deployment state is not healthy or is pending" >&2
                exit 1
            fi
            ;;

        *)
            echo "Unknown travel deployment layout: $workdir" >&2
            exit 1
            ;;
    esac

    echo "Travel deployment mode: $TRAVEL_MODE"
    echo "Travel application path: $TRAVEL_RELEASE"
}

backup_environment() {
    section "Environment Backup"

    cp "$BASE_DIR/google-map-searcher/.env" \
        "$TEMP_DIR/environment/linebot.env"

    if [[ "$TRAVEL_MODE" == release ]]; then
        sudo -n -u travel-app /usr/bin/cat \
            /opt/travel-app/shared/.env \
            > "$TEMP_DIR/environment/travel.env"
    else
        cp "$BASE_DIR/travel_app/.env" \
            "$TEMP_DIR/environment/travel.env"
    fi

    if [[ "$TRAVEL_MODE" == release ]]; then
        printf 'VITE_API_URL=\n' \
            > "$TEMP_DIR/environment/travel-frontend.env.production"
    else
        cp "$BASE_DIR/travel_app/frontend/.env.production" \
            "$TEMP_DIR/environment/travel-frontend.env.production"
    fi

    cp "$BASE_DIR/link_manager/.env" \
        "$TEMP_DIR/environment/link_manager.env"

    chmod 600 "$TEMP_DIR/environment/"*

    echo "Environment files: PASS"
}

# ========================================
# Configuration Backup
# ========================================



backup_config() {
    section "Configuration Backup"

    # Nginx
    sudo -n /usr/bin/tar -czf - \
        -C /etc nginx \
        > "$TEMP_DIR/config/nginx.tar.gz"

    echo "Nginx: PASS"

    # Systemd services and backup timer
    sudo -n /usr/bin/tar -czf - \
        -C /etc/systemd/system \
        linebot.service \
        travel.service \
        link_manager.service \
        server-backup.service \
        server-backup.timer \
        > "$TEMP_DIR/config/systemd.tar.gz"

    echo "Systemd services and timer: PASS"

    # SSL certificates
    sudo -n /usr/bin/tar -czf - \
        -C /etc letsencrypt \
        > "$TEMP_DIR/config/letsencrypt.tar.gz"

    echo "Let's Encrypt: PASS"

    # Journald configuration
    sudo -n /usr/bin/tar -czf - \
        -C /etc/systemd \
        journald.conf \
        journald.conf.d \
        > "$TEMP_DIR/config/journald.tar.gz"

    echo "Journald configuration: PASS"

    # Backup sudoers configuration
    sudo -n /usr/bin/tar -czf - \
        -C /etc sudoers.d/server-backup \
        > "$TEMP_DIR/config/sudoers.tar.gz"

    echo "Backup sudoers configuration: PASS"

    sudo -n /usr/bin/tar -czf - -C / \
        usr/local/bin/travel-deploy-entry \
        usr/local/sbin/travel-deploy-control \
        etc/sudoers.d/travel-deploy \
        opt/travel-app/tools \
        > "$TEMP_DIR/config/travel-deployment.tar.gz"

    echo "Travel deployment tools: PASS"

    sudo -n /usr/local/sbin/travel-backup-deployment-archive \
        > "$TEMP_DIR/config/travel-deployment-state.tar.gz"
    echo "Travel deployment state and additional tools: PASS"
}



# ========================================
# Firewall Backup
# ========================================

backup_firewall() {
    section "Firewall Backup"

    sudo -n /usr/sbin/iptables-save \
        > "$TEMP_DIR/firewall/iptables.rules"

    echo "IPv4 firewall: PASS"

    sudo -n /usr/sbin/ip6tables-save \
        > "$TEMP_DIR/firewall/ip6tables.rules"

    echo "IPv6 firewall: PASS"

    sudo -n /usr/bin/tar -czf - \
        -C /etc iptables \
        > "$TEMP_DIR/firewall/persistent.tar.gz"

    echo "Persistent firewall rules: PASS"
}

# ========================================
# Application Data Backup
# ========================================

backup_data() {
    section "Application Data Backup"

    # User uploaded files
    if [[ "$TRAVEL_MODE" == release ]]; then
        sudo -n -u travel-app /usr/bin/tar -czf - \
            -C /opt/travel-app/shared uploads \
            > "$TEMP_DIR/data/travel-uploads.tar.gz"
    else
        tar -czf "$TEMP_DIR/data/travel-uploads.tar.gz" \
            -C "$BASE_DIR/travel_app" uploads
    fi

    echo "Travel uploads: PASS"

    # Production frontend
    tar -czf "$TEMP_DIR/data/travel-dist.tar.gz" \
        -C "$TRAVEL_RELEASE" dist

    echo "Travel frontend: PASS"
}

# ========================================
# Dependency and Version Backup
# ========================================

backup_metadata() {
    section "Metadata Backup"

    local project

    # Python dependencies
    "$BASE_DIR/google-map-searcher/.venv/bin/python" \
        -m pip freeze \
        > "$TEMP_DIR/metadata/linebot-requirements.txt"

    if [[ "$TRAVEL_MODE" == release ]]; then
        sudo -n /usr/local/sbin/travel-backup-guard packages \
            > "$TEMP_DIR/metadata/travel-requirements.txt"
    else
        "$TRAVEL_RELEASE/venv/bin/python" -m pip freeze \
            > "$TEMP_DIR/metadata/travel-requirements.txt"
    fi

    "$BASE_DIR/link_manager/venv/bin/python" \
        -m pip freeze \
        > "$TEMP_DIR/metadata/link_manager-requirements.txt"

    echo "Python dependencies: PASS"

    # Git versions
    for project in "${PROJECTS[@]}"; do

        {
            echo "[$project]"

            git -C "$BASE_DIR/$project" rev-parse HEAD

            git -C "$BASE_DIR/$project" status --short

            echo ""

        } >> "$TEMP_DIR/metadata/git-versions.txt"

    done

    {
        echo "[travel_app]"
        if [[ "$TRAVEL_MODE" == release ]]; then
            cat "$TRAVEL_RELEASE/REVISION"
            echo "Deployment mode: release"
        else
            git -C "$TRAVEL_RELEASE" rev-parse HEAD
            git -C "$TRAVEL_RELEASE" status --short
        fi
        echo ""
    } >> "$TEMP_DIR/metadata/git-versions.txt"

    if [[ "$TRAVEL_MODE" == release ]]; then
        cp "$TRAVEL_RELEASE/REVISION" \
            "$TEMP_DIR/metadata/travel-revision.txt"
    fi

    echo "Git versions: PASS"

    # System information
    {
        echo "[Hostname]"
        hostname

        echo ""
        echo "[Backup Time]"
        date -u

        echo ""
        echo "[Kernel]"
        uname -a

        echo ""
        echo "[Operating System]"
        cat /etc/os-release

        echo ""
        echo "[Python]"
        python3 --version

        echo ""
        echo "[PostgreSQL]"
        pg_dump --version

        echo ""
        echo "[Nginx]"
        nginx -v 2>&1

        echo ""
        echo "[Node.js]"

        if command -v node >/dev/null 2>&1; then
            node --version
        else
            echo "Node.js not available in PATH"
        fi

        echo ""
        echo "[Disk Usage]"
        df -h /

        echo ""
        echo "[Memory Usage]"
        free -h

    } > "$TEMP_DIR/metadata/system-info.txt"

    echo "System information: PASS"
}

# ========================================
# Maintenance Scripts
# ========================================

backup_scripts() {
    section "Maintenance Scripts"

    cp -a "$BASE_DIR/scripts/server-status.sh" \
        "$TEMP_DIR/scripts/"

    cp -a "$BASE_DIR/scripts/backup.sh" \
        "$TEMP_DIR/scripts/"

    echo "Maintenance scripts: PASS"
}

# ========================================
# Backup Verification
# ========================================

verify_backup() {
    section "Backup Verification"

    local archive
    local archives

    # Verify compressed archives
    archives=$(find "$TEMP_DIR" \
        -type f -name '*.tar.gz' -print)

    while IFS= read -r archive; do

        [[ -n "$archive" ]] || continue

        gzip -t "$archive"

        tar -tzf "$archive" > /dev/null

        echo "$(basename "$archive"): PASS"

    done <<< "$archives"

    # Generate and verify checksums
    (
        cd "$TEMP_DIR"

        find . -type f \
            ! -name SHA256SUMS \
            -print0 |
            sort -z |
            xargs -0 -r sha256sum > SHA256SUMS

        test -s SHA256SUMS

        sha256sum -c SHA256SUMS
    )

    echo "Backup verification: PASS"
}

# ========================================
# Publish Backup
# ========================================

publish_backup() {
    section "Backup Summary"

    if [[ -e "$BACKUP_DIR" ]]; then
        echo "Backup destination already exists" >&2
        exit 1
    fi

    mv -T -- "$TEMP_DIR" "$BACKUP_DIR"

    TEMP_DIR=""

    echo "Backup directory: $BACKUP_DIR"

    du -sh "$BACKUP_DIR"

    echo ""
    echo "BACKUP COMPLETE"
}

# ========================================
# Safe Backup Removal
# ========================================

remove_backup() {
    local target="$1"
    local name="${target##*/}"

    # Must be a direct child of BACKUP_ROOT
    if [[ "${target%/*}" != "$BACKUP_ROOT" ]]; then
        echo "Unsafe backup path: $target" >&2
        return 1
    fi

    # Must be a real directory, not a symlink
    if [[ ! -d "$target" || -L "$target" ]]; then
        echo "Invalid backup directory: $target" >&2
        return 1
    fi

    # Validate directory name
    if ! [[ "$name" =~ ^[0-9]{8}-[0-9]{6}$ ||
            "$name" =~ ^\.incomplete-[0-9]{8}-[0-9]{6}-[a-zA-Z0-9]+$ ]]; then

        echo "Invalid backup name: $name" >&2
        return 1

    fi

    # Never remove the current backup
    if [[ "$target" == "$BACKUP_DIR" ]]; then
        echo "Refusing to remove current backup" >&2
        return 1
    fi

    # Dry run mode
    if [[ "$DRY_RUN" == true ]]; then

        echo "[DRY RUN] Would remove: $target"

    else

        rm -rf -- "$target"

        echo "Removed: $target"

    fi
}

# ========================================
# Backup Retention
# ========================================

rotate_backups() {
    section "Backup Retention"

    local cutoff
    local backup
    local name
    local listing
    local incomplete_listing
    local index=0

    cutoff=$(date -u \
        -d "$RETENTION_DAYS days ago" \
        +%Y%m%d-%H%M%S)

    echo "Retention: $RETENTION_DAYS days"
    echo "Minimum backups: $MIN_BACKUPS"
    echo "Dry run: $DRY_RUN"
    echo "Cutoff: $cutoff UTC"

    # Sort newest backups first
    listing=$(find "$BACKUP_ROOT" \
        -mindepth 1 \
        -maxdepth 1 \
        -type d \
        -printf '%f\n' |
        sort -r)

    while IFS= read -r name; do

        [[ "$name" =~ ^[0-9]{8}-[0-9]{6}$ ]] ||
            continue

        backup="$BACKUP_ROOT/$name"

        # Skip backups without checksum manifests
        if [[ ! -s "$backup/SHA256SUMS" ]]; then

            echo "Skipping unverified directory: $name"

            continue

        fi

        ((index += 1))

        # Protect newest backups
        if (( index <= MIN_BACKUPS )); then

            echo "Protected: $name"

            continue

        fi

        # Check retention period
        if [[ "$name" < "$cutoff" ]]; then

            remove_backup "$backup"

        else

            echo "Retained: $name"

        fi

    done <<< "$listing"

    # Check incomplete backups
    section "Incomplete Backup Check"

    incomplete_listing=$(find "$BACKUP_ROOT" \
        -mindepth 1 \
        -maxdepth 1 \
        -type d \
        -name '.incomplete-*' \
        -mmin "+$((INCOMPLETE_RETENTION_DAYS * 1440))" \
        -print)

    while IFS= read -r backup; do

        [[ -n "$backup" ]] || continue

        remove_backup "$backup"

    done <<< "$incomplete_listing"

    echo "Backup retention check: COMPLETE"
}

# ========================================
# Main
# ========================================

main() {
    echo "========================================"
    echo "           SERVER BACKUP V6"
    echo "========================================"

    acquire_lock
    acquire_lifecycle_lock
    detect_travel_layout
    check_disk_space
    prepare_backup

    backup_databases
    backup_environment
    backup_config
    backup_firewall
    backup_data
    backup_metadata
    backup_scripts

    verify_backup
    publish_backup

    rotate_backups

    echo ""
    echo "========================================"
    echo "     ALL BACKUP OPERATIONS COMPLETE"
    echo "========================================"
}

main

