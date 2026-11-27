from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import app, db

# 建立應用程式上下文，並執行原生 SQL 指令
with app.app_context():
    try:
        # 執行修改表格的指令
        db.session.execute(text("ALTER TABLE trip ADD COLUMN user_id INTEGER REFERENCES users(id);"))
        db.session.commit()
        print("🎉 太棒了！資料庫升級成功！")
    except SQLAlchemyError as error:
        db.session.rollback()
        print("發生錯誤（可能已經新增過，或者資料庫沒開啟）:", error)
