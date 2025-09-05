from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone, timedelta
import os

db = SQLAlchemy()

# 获取本地时间（中国时区）
def get_local_time():
    return datetime.now(timezone(timedelta(hours=8)))

class RoomMember(db.Model):
    __tablename__ = 'room_members'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), primary_key=True)
    joined_at = db.Column(db.DateTime, default=get_local_time)
    is_pinned = db.Column(db.Boolean, default=False)
    last_read_at = db.Column(db.DateTime, default=get_local_time)
    
    # 关系
    user = db.relationship('User', backref='user_rooms')
    room = db.relationship('Room', backref='room_users')

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=get_local_time)
    
    # 关系
    messages = db.relationship('Message', backref='author', lazy=True)
    owned_rooms = db.relationship('Room', backref='owner', lazy=True)
    sent_invitations = db.relationship('Invitation', foreign_keys='Invitation.sender_id', backref='sender', lazy=True)
    received_invitations = db.relationship('Invitation', foreign_keys='Invitation.receiver_id', backref='receiver', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'is_admin': self.is_admin,
            'created_at': self.created_at.isoformat()
        }
    
    def get_rooms_with_status(self):
        """获取用户的聊天室列表，包含置顶和未读状态"""
        room_members = RoomMember.query.filter_by(user_id=self.id).all()
        rooms_data = []
        
        for rm in room_members:
            room = rm.room
            # 获取最新消息时间
            latest_message = Message.query.filter_by(room_id=room.id, revoked=False)\
                                        .order_by(Message.created_at.desc()).first()
            
            has_unread = False
            if latest_message and rm.last_read_at and latest_message.created_at > rm.last_read_at:
                has_unread = True
            elif latest_message and not rm.last_read_at:
                # 如果从未阅读过，则有未读消息
                has_unread = True
            
            room_dict = room.to_dict()
            room_dict['is_pinned'] = rm.is_pinned
            room_dict['has_unread'] = has_unread
            room_dict['last_read_at'] = rm.last_read_at.isoformat() if rm.last_read_at else None
            
            rooms_data.append(room_dict)
        
        return rooms_data

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    is_main = db.Column(db.Boolean, default=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=get_local_time)
    
    # 关系
    messages = db.relationship('Message', backref='room', lazy=True, cascade='all, delete-orphan')
    invitations = db.relationship('Invitation', backref='room', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        member_count = RoomMember.query.filter_by(room_id=self.id).count()
        return {
            'id': self.id,
            'name': self.name,
            'is_main': self.is_main,
            'owner_id': self.owner_id,
            'member_count': member_count,
            'created_at': self.created_at.isoformat()
        }
    
    def get_members(self):
        """获取聊天室成员列表"""
        room_members = RoomMember.query.filter_by(room_id=self.id).all()
        return [rm.user for rm in room_members]

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text)
    message_type = db.Column(db.String(20), default='text')  # text, image, file, emoji
    file_path = db.Column(db.String(200))
    file_name = db.Column(db.String(100))
    revoked = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=get_local_time)
    
    # 外键
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'content': self.content,
            'message_type': self.message_type,
            'file_path': self.file_path,
            'file_name': self.file_name,
            'revoked': self.revoked,
            'created_at': self.created_at.isoformat(),
            'user_id': self.user_id,
            'room_id': self.room_id,
            'author': self.author.username if self.author else None
        }

class Invitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, rejected
    created_at = db.Column(db.DateTime, default=get_local_time)
    
    # 外键
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'sender_id': self.sender_id,
            'receiver_id': self.receiver_id,
            'room_id': self.room_id,
            'sender_name': self.sender.username if self.sender else None,
            'room_name': self.room.name if self.room else None
        }
