#!/usr/bin/env python3
"""
数据库初始化脚本
重新创建所有表格以支持新的数据模型
"""

import os
from app import app, db
from models import User, Room, Message, Invitation, RoomMember
from datetime import datetime

def init_database():
    with app.app_context():
        # 删除所有现有表
        print("删除现有表...")
        db.drop_all()
        
        # 重新创建所有表
        print("创建新表...")
        db.create_all()
        
        # 创建总聊天室
        print("创建总聊天室...")
        main_room = Room(
            name="总聊天室",
            is_main=True,
            owner_id=None
        )
        db.session.add(main_room)
        db.session.commit()
        
        # 创建默认管理员账户
        print("创建默认管理员账户...")
        admin_user = User(
            username="admin",
            password="zzj20120111",
            is_admin=True
        )
        db.session.add(admin_user)
        db.session.commit()
        
        print("数据库初始化完成！")
        print(f"总聊天室ID: {main_room.id}")
        print("默认管理员账户: admin/zzj20120111")

if __name__ == "__main__":
    init_database()
