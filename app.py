from flask import Flask, jsonify
from flask_cors import CORS  # 导入CORS
import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from models import db, User, Room, Message, Invitation, RoomMember, get_local_time
from datetime import datetime, timedelta, timezone
import os
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# 配置
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chatroom.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB 最大文件大小

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'zip', 'rar'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 初始化数据库
db.init_app(app)

# 用户注册
@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not username or not password:
            return jsonify({'error': '用户名和密码不能为空'}), 400
        
        if len(username) < 3 or len(username) > 20:
            return jsonify({'error': '用户名长度必须在3-20个字符之间'}), 400
        
        if len(password) < 6:
            return jsonify({'error': '密码长度至少6个字符'}), 400
        
        # 检查用户名是否已存在
        if User.query.filter_by(username=username).first():
            return jsonify({'error': '用户名已存在'}), 400
        
        # 创建新用户
        user = User(username=username, password=password)
        db.session.add(user)
        db.session.commit()
        
        # 自动加入总聊天室
        main_room = Room.query.filter_by(is_main=True).first()
        if main_room:
            room_member = RoomMember(user_id=user.id, room_id=main_room.id)
            db.session.add(room_member)
            db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': '注册成功',
            'user': user.to_dict()
        })
    
    except Exception as e:
        return jsonify({'error': f'注册失败: {str(e)}'}), 500

# 用户登录
@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not username or not password:
            return jsonify({'error': '用户名和密码不能为空'}), 400
        
        user = User.query.filter_by(username=username, password=password).first()
        if not user:
            return jsonify({'error': '用户名或密码错误'}), 400
        
        return jsonify({
            'success': True,
            'user_id': user.id,
            'username': user.username,
            'is_admin': user.is_admin,
            'message': '登录成功'
        })
    
    except Exception as e:
        return jsonify({'error': f'登录失败: {str(e)}'}), 500

# 获取用户的聊天室列表
@app.route('/api/rooms', methods=['GET'])
def get_user_rooms():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'error': '用户ID不能为空'}), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': '用户不存在'}), 404
        
        rooms_data = user.get_rooms_with_status()
        return jsonify({'rooms': rooms_data})
    
    except Exception as e:
        return jsonify({'error': f'获取聊天室列表失败: {str(e)}'}), 500

# 获取聊天室消息
@app.route('/api/messages', methods=['GET'])
def get_messages():
    try:
        room_id = request.args.get('room_id')
        user_id = request.args.get('user_id')
        
        if not room_id or not user_id:
            return jsonify({'error': '房间ID和用户ID不能为空'}), 400
        
        room = Room.query.get(room_id)
        user = User.query.get(user_id)
        
        if not room or not user:
            return jsonify({'error': '房间或用户不存在'}), 404
        
        # 检查用户是否是房间成员
        room_member = RoomMember.query.filter_by(user_id=user_id, room_id=room_id).first()
        if not room_member:
            return jsonify({'error': '您不是该聊天室的成员'}), 403
        
        # 根据房间类型决定消息数量限制
        limit = 100 if room.is_main else 50
        
        messages = Message.query.filter_by(room_id=room_id, revoked=False)\
                         .order_by(Message.created_at.desc())\
                         .limit(limit).all()
        
        messages_data = [msg.to_dict() for msg in reversed(messages)]
        return jsonify({'messages': messages_data})
    
    except Exception as e:
        return jsonify({'error': f'获取消息失败: {str(e)}'}), 500

# 管理员获取聊天室消息（用于监控）
@app.route('/api/admin/messages', methods=['GET'])
def admin_get_messages():
    try:
        admin_id = request.args.get('admin_id')
        room_id = request.args.get('room_id')
        
        if not admin_id or not room_id:
            return jsonify({'error': '管理员ID和房间ID不能为空'}), 400
        
        admin = User.query.get(admin_id)
        if not admin or not admin.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'error': '房间不存在'}), 404
        
        # 管理员可以查看更多消息历史
        limit = 200
        
        messages = Message.query.filter_by(room_id=room_id, revoked=False)\
                         .order_by(Message.created_at.desc())\
                         .limit(limit).all()
        
        messages_data = [msg.to_dict() for msg in reversed(messages)]
        return jsonify({
            'messages': messages_data,
            'room_name': room.name,
            'room_id': room_id
        })
    
    except Exception as e:
        return jsonify({'error': f'获取消息失败: {str(e)}'}), 500

# 发送消息
@app.route('/api/send_message', methods=['POST'])
def send_message():
    try:
        user_id = request.form.get('user_id')
        room_id = request.form.get('room_id')
        content = request.form.get('content', '')
        message_type = request.form.get('message_type', 'text')
        
        if not user_id or not room_id:
            return jsonify({'error': '用户ID和房间ID不能为空'}), 400
        
        user = User.query.get(user_id)
        room = Room.query.get(room_id)
        
        if not user or not room:
            return jsonify({'error': '用户或房间不存在'}), 404
        
        # 检查用户是否是房间成员
        room_member = RoomMember.query.filter_by(user_id=user_id, room_id=room_id).first()
        if not room_member:
            return jsonify({'error': '您不是该聊天室的成员'}), 403
        
        file_path = None
        file_name = None
        
        # 处理文件上传
        if message_type in ['image', 'file'] and 'file' in request.files:
            file = request.files['file']
            if file and file.filename and allowed_file(file.filename):
                # 生成唯一文件名
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4()}_{filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(file_path)
                file_name = filename
                file_path = unique_filename
            else:
                return jsonify({'error': '不支持的文件类型'}), 400
        
        # 创建消息
        message = Message(
            content=content,
            message_type=message_type,
            file_path=file_path,
            file_name=file_name,
            user_id=user_id,
            room_id=room_id
        )
        
        db.session.add(message)
        db.session.commit()
        
        return jsonify({'success': True, 'message': message.to_dict()})
    
    except Exception as e:
        return jsonify({'error': f'发送消息失败: {str(e)}'}), 500

# 撤回消息
@app.route('/api/revoke_message', methods=['POST'])
def revoke_message():
    try:
        data = request.get_json()
        message_id = data.get('message_id')
        user_id = data.get('user_id')
        
        if not message_id or not user_id:
            return jsonify({'error': '消息ID和用户ID不能为空'}), 400
        
        message = Message.query.get(message_id)
        if not message:
            return jsonify({'error': '消息不存在'}), 404
        
        # 检查是否是消息发送者
        if message.user_id != int(user_id):
            return jsonify({'error': '只能撤回自己的消息'}), 403
        
        # 检查是否在2分钟内
        time_diff = get_local_time().replace(tzinfo=None) - message.created_at.replace(tzinfo=None)
        if time_diff > timedelta(minutes=2):
            return jsonify({'error': '超过2分钟无法撤回'}), 400
        
        message.revoked = True
        db.session.commit()
        
        return jsonify({'success': True, 'message': '消息撤回成功'})
    
    except Exception as e:
        return jsonify({'error': f'撤回消息失败: {str(e)}'}), 500

# 获取聊天室成员
@app.route('/api/room_members', methods=['GET'])
def get_room_members():
    try:
        room_id = request.args.get('room_id')
        user_id = request.args.get('user_id')
        
        if not room_id or not user_id:
            return jsonify({'error': '房间ID和用户ID不能为空'}), 400
        
        room = Room.query.get(room_id)
        user = User.query.get(user_id)
        
        if not room or not user:
            return jsonify({'error': '房间或用户不存在'}), 404
        
        # 检查用户是否是房间成员
        room_member = RoomMember.query.filter_by(user_id=user_id, room_id=room_id).first()
        if not room_member:
            return jsonify({'error': '您不是该聊天室的成员'}), 403
        
        members = room.get_members()
        members_data = [member.to_dict() for member in members]
        return jsonify({
            'members': members_data,
            'room': room.to_dict()
        })
    
    except Exception as e:
        return jsonify({'error': f'获取成员列表失败: {str(e)}'}), 500

# 创建聊天室
@app.route('/api/create_room', methods=['POST'])
def create_room():
    try:
        data = request.get_json()
        room_name = data.get('room_name', '').strip()
        user_id = data.get('user_id')
        
        if not room_name or not user_id:
            return jsonify({'error': '房间名称和用户ID不能为空'}), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': '用户不存在'}), 404
        
        # 创建新聊天室
        room = Room(name=room_name, owner_id=user_id)
        db.session.add(room)
        db.session.flush()  # 获取room.id
        
        # 将创建者加入聊天室
        room_member = RoomMember(user_id=user_id, room_id=room.id)
        db.session.add(room_member)
        db.session.commit()
        
        return jsonify({'success': True, 'room': room.to_dict()})
    
    except Exception as e:
        return jsonify({'error': f'创建聊天室失败: {str(e)}'}), 500

# 发送邀请
@app.route('/api/send_invitation', methods=['POST'])
def send_invitation():
    try:
        data = request.get_json()
        sender_id = data.get('sender_id')
        receiver_username = data.get('receiver_username', '').strip()
        room_id = data.get('room_id')
        
        if not sender_id or not receiver_username or not room_id:
            return jsonify({'error': '发送者ID、接收者用户名和房间ID不能为空'}), 400
        
        sender = User.query.get(sender_id)
        receiver = User.query.filter_by(username=receiver_username).first()
        room = Room.query.get(room_id)
        
        if not sender or not receiver or not room:
            return jsonify({'error': '发送者、接收者或房间不存在'}), 404
        
        # 检查发送者是否是房间成员
        sender_member = RoomMember.query.filter_by(user_id=sender_id, room_id=room_id).first()
        if not sender_member:
            return jsonify({'error': '您不是该聊天室的成员'}), 403
        
        # 检查接收者是否已经是房间成员
        receiver_member = RoomMember.query.filter_by(user_id=receiver.id, room_id=room_id).first()
        if receiver_member:
            return jsonify({'error': '该用户已经是聊天室成员'}), 400
        
        # 检查是否已有待处理的邀请
        existing_invitation = Invitation.query.filter_by(
            sender_id=sender_id,
            receiver_id=receiver.id,
            room_id=room_id,
            status='pending'
        ).first()
        
        if existing_invitation:
            return jsonify({'error': '已有待处理的邀请'}), 400
        
        # 创建邀请
        invitation = Invitation(
            sender_id=sender_id,
            receiver_id=receiver.id,
            room_id=room_id
        )
        
        db.session.add(invitation)
        db.session.commit()
        
        return jsonify({'success': True, 'message': '邀请发送成功'})
    
    except Exception as e:
        return jsonify({'error': f'发送邀请失败: {str(e)}'}), 500

# 获取用户的邀请列表
@app.route('/api/invitations', methods=['GET'])
def get_invitations():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'error': '用户ID不能为空'}), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': '用户不存在'}), 404
        
        invitations = Invitation.query.filter_by(receiver_id=user_id, status='pending')\
                                    .order_by(Invitation.created_at.desc()).all()
        
        invitations_data = [inv.to_dict() for inv in invitations]
        return jsonify({'invitations': invitations_data})
    
    except Exception as e:
        return jsonify({'error': f'获取邀请列表失败: {str(e)}'}), 500

# 处理邀请
@app.route('/api/handle_invitation', methods=['POST'])
def handle_invitation():
    try:
        data = request.get_json()
        invitation_id = data.get('invitation_id')
        user_id = data.get('user_id')
        action = data.get('action')  # 'accept' or 'reject'
        
        if not invitation_id or not user_id or not action:
            return jsonify({'error': '邀请ID、用户ID和操作不能为空'}), 400
        
        invitation = Invitation.query.get(invitation_id)
        if not invitation:
            return jsonify({'error': '邀请不存在'}), 404
        
        # 检查是否是邀请接收者
        if invitation.receiver_id != int(user_id):
            return jsonify({'error': '无权处理此邀请'}), 403
        
        if invitation.status != 'pending':
            return jsonify({'error': '邀请已被处理'}), 400
        
        if action == 'accept':
            invitation.status = 'accepted'
            # 将用户加入聊天室
            room_member = RoomMember(user_id=user_id, room_id=invitation.room_id)
            db.session.add(room_member)
        elif action == 'reject':
            invitation.status = 'rejected'
        else:
            return jsonify({'error': '无效的操作'}), 400
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'邀请已{action}'})
    
    except Exception as e:
        return jsonify({'error': f'处理邀请失败: {str(e)}'}), 500

# 踢出成员
@app.route('/api/kick_member', methods=['POST'])
def kick_member():
    try:
        data = request.get_json()
        room_id = data.get('room_id')
        kicker_id = data.get('kicker_id')
        member_id = data.get('member_id')
        
        if not room_id or not kicker_id or not member_id:
            return jsonify({'error': '房间ID、踢人者ID和被踢者ID不能为空'}), 400
        
        room = Room.query.get(room_id)
        kicker = User.query.get(kicker_id)
        member = User.query.get(member_id)
        
        if not room or not kicker or not member:
            return jsonify({'error': '房间或用户不存在'}), 404
        
        # 检查是否是房主
        if room.owner_id != int(kicker_id):
            return jsonify({'error': '只有房主可以踢出成员'}), 403
        
        # 不能踢出自己
        if kicker_id == member_id:
            return jsonify({'error': '不能踢出自己'}), 400
        
        # 检查被踢者是否是房间成员
        member_relation = RoomMember.query.filter_by(user_id=member_id, room_id=room_id).first()
        if not member_relation:
            return jsonify({'error': '该用户不是聊天室成员'}), 400
        
        # 踢出成员
        db.session.delete(member_relation)
        db.session.commit()
        
        return jsonify({'success': True, 'message': '成员已被踢出'})
    
    except Exception as e:
        return jsonify({'error': f'踢出成员失败: {str(e)}'}), 500

# 更改聊天室名称
@app.route('/api/update_room_name', methods=['POST'])
def update_room_name():
    try:
        data = request.get_json()
        room_id = data.get('room_id')
        user_id = data.get('user_id')
        new_name = data.get('new_name', '').strip()
        
        if not room_id or not user_id or not new_name:
            return jsonify({'error': '房间ID、用户ID和新名称不能为空'}), 400
        
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'error': '房间不存在'}), 404
        
        # 检查是否是总聊天室
        if room.is_main:
            return jsonify({'error': '总聊天室名称不可更改'}), 403
        
        # 检查是否是房主
        if room.owner_id != int(user_id):
            return jsonify({'error': '只有房主可以更改聊天室名称'}), 403
        
        room.name = new_name
        db.session.commit()
        
        return jsonify({'success': True, 'message': '聊天室名称更新成功', 'room': room.to_dict()})
    
    except Exception as e:
        return jsonify({'error': f'更新聊天室名称失败: {str(e)}'}), 500

# 删除聊天室
@app.route('/api/delete_room', methods=['POST'])
def delete_room():
    try:
        data = request.get_json()
        room_id = data.get('room_id')
        user_id = data.get('user_id')
        
        if not room_id or not user_id:
            return jsonify({'error': '房间ID和用户ID不能为空'}), 400
        
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'error': '房间不存在'}), 404
        
        # 检查是否是总聊天室
        if room.is_main:
            return jsonify({'error': '总聊天室不能删除'}), 403
        
        # 检查是否是房主
        if room.owner_id != int(user_id):
            return jsonify({'error': '只有房主可以删除聊天室'}), 403
        
        # 手动删除相关记录以避免外键约束问题
        # 1. 删除房间成员记录
        RoomMember.query.filter_by(room_id=room_id).delete()
        
        # 2. 删除房间消息记录
        Message.query.filter_by(room_id=room_id).delete()
        
        # 3. 删除房间邀请记录
        Invitation.query.filter_by(room_id=room_id).delete()
        
        # 4. 最后删除房间本身
        db.session.delete(room)
        
        # 提交所有更改
        db.session.commit()
        
        return jsonify({'success': True, 'message': '聊天室删除成功'})
    
    except Exception as e:
        db.session.rollback()
        print(f"删除聊天室错误: {str(e)}")  # 添加调试输出
        return jsonify({'error': f'删除聊天室失败: {str(e)}'}), 500

# 文件下载
@app.route('/api/download/<filename>')
def download_file(filename):
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)
    except Exception as e:
        return jsonify({'error': f'文件下载失败: {str(e)}'}), 404

# 搜索用户
@app.route('/api/search_users', methods=['GET'])
def search_users():
    try:
        query = request.args.get('query', '').strip()
        if not query:
            return jsonify({'users': []})
        
        users = User.query.filter(User.username.like(f'%{query}%')).limit(10).all()
        users_data = [user.to_dict() for user in users]
        
        return jsonify({'users': users_data})
    
    except Exception as e:
        return jsonify({'error': f'搜索用户失败: {str(e)}'}), 500

# 置顶/取消置顶聊天室
@app.route('/api/toggle_pin_room', methods=['POST'])
def toggle_pin_room():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        room_id = data.get('room_id')
        
        if not user_id or not room_id:
            return jsonify({'error': '用户ID和房间ID不能为空'}), 400
        
        room_member = RoomMember.query.filter_by(user_id=user_id, room_id=room_id).first()
        if not room_member:
            return jsonify({'error': '您不是该聊天室的成员'}), 403
        
        # 检查是否是总聊天室
        room = Room.query.get(room_id)
        if room and room.is_main:
            return jsonify({'error': '总聊天室不能置顶'}), 400
        
        # 切换置顶状态
        room_member.is_pinned = not room_member.is_pinned
        db.session.commit()
        
        action = '置顶' if room_member.is_pinned else '取消置顶'
        return jsonify({
            'success': True, 
            'message': f'聊天室{action}成功',
            'is_pinned': room_member.is_pinned
        })
    
    except Exception as e:
        return jsonify({'error': f'操作失败: {str(e)}'}), 500

# 标记消息已读
@app.route('/api/mark_read', methods=['POST'])
def mark_read():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        room_id = data.get('room_id')
        
        if not user_id or not room_id:
            return jsonify({'error': '用户ID和房间ID不能为空'}), 400
        
        room_member = RoomMember.query.filter_by(user_id=user_id, room_id=room_id).first()
        if not room_member:
            return jsonify({'error': '您不是该聊天室的成员'}), 403
        
        # 更新最后阅读时间
        room_member.last_read_at = get_local_time()
        db.session.commit()
        
        return jsonify({'success': True, 'message': '标记已读成功'})
    
    except Exception as e:
        return jsonify({'error': f'标记已读失败: {str(e)}'}), 500

@app.route('/api/available_users', methods=['GET'])
def get_available_users():
    try:
        room_id = request.args.get('room_id')
        
        if not room_id:
            return jsonify({'error': '房间ID不能为空'}), 400
        
        # 获取房间信息
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'error': '房间不存在'}), 404
        
        # 获取房间中的所有成员ID
        current_member_ids = db.session.query(RoomMember.user_id).filter_by(room_id=room_id).all()
        current_member_ids = [member[0] for member in current_member_ids]
        
        # 获取已经有未处理邀请的用户ID（状态为pending的邀请）
        pending_invitation_user_ids = db.session.query(Invitation.receiver_id).filter_by(
            room_id=room_id, 
            status='pending'
        ).all()
        pending_invitation_user_ids = [invitation[0] for invitation in pending_invitation_user_ids]
        
        # 合并排除列表：既不在房间中，也没有未处理的邀请
        excluded_user_ids = current_member_ids + pending_invitation_user_ids
        
        # 获取所有可邀请的用户（不在房间中且没有未处理邀请）
        if excluded_user_ids:
            available_users = User.query.filter(~User.id.in_(excluded_user_ids)).all()
        else:
            # 如果没有需要排除的用户，获取所有用户
            available_users = User.query.all()
        
        users_data = []
        for user in available_users:
            users_data.append({
                'id': user.id,
                'username': user.username,
                'created_at': user.created_at.strftime('%Y-%m-%d') if user.created_at else ''
            })
        
        return jsonify({'users': users_data})
        
    except Exception as e:
        return jsonify({'error': f'获取用户列表失败: {str(e)}'}), 500

# 注销账户
@app.route('/api/delete_account', methods=['POST'])
def delete_account():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        password = data.get('password')
        
        if not user_id or not password:
            return jsonify({'error': '用户ID和密码不能为空'}), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': '用户不存在'}), 404
        
        # 验证密码
        if user.password != password:
            return jsonify({'error': '密码错误'}), 403
        
        # 删除用户拥有的聊天室（非总聊天室）
        owned_rooms = Room.query.filter_by(owner_id=user_id, is_main=False).all()
        for room in owned_rooms:
            db.session.delete(room)
        
        # 从所有聊天室中移除用户
        RoomMember.query.filter_by(user_id=user_id).delete()
        
        # 删除用户发送的所有消息
        Message.query.filter_by(user_id=user_id).delete()
        
        # 删除用户的所有邀请
        Invitation.query.filter((Invitation.sender_id == user_id) | (Invitation.receiver_id == user_id)).delete()
        
        # 删除用户账户
        db.session.delete(user)
        db.session.commit()
        
        return jsonify({'success': True, 'message': '账户注销成功'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'账户注销失败: {str(e)}'}), 500

# ==================== 管理员功能 ====================

# 获取所有用户列表（管理员专用）
@app.route('/api/admin/users', methods=['GET'])
def admin_get_all_users():
    try:
        admin_id = request.args.get('admin_id')
        if not admin_id:
            return jsonify({'error': '管理员ID不能为空'}), 400
        
        admin = User.query.get(admin_id)
        if not admin or not admin.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        users = User.query.all()
        users_data = []
        for user in users:
            user_dict = user.to_dict()
            # 添加用户所在的聊天室数量
            room_count = RoomMember.query.filter_by(user_id=user.id).count()
            user_dict['room_count'] = room_count
            users_data.append(user_dict)
        
        return jsonify({'users': users_data})
    
    except Exception as e:
        return jsonify({'error': f'获取用户列表失败: {str(e)}'}), 500

# 获取所有聊天室列表（管理员专用）
@app.route('/api/admin/rooms', methods=['GET'])
def admin_get_all_rooms():
    try:
        admin_id = request.args.get('admin_id')
        if not admin_id:
            return jsonify({'error': '管理员ID不能为空'}), 400
        
        admin = User.query.get(admin_id)
        if not admin or not admin.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        rooms = Room.query.all()
        rooms_data = []
        for room in rooms:
            room_dict = room.to_dict()
            # 添加房主名称
            if room.owner_id:
                owner = User.query.get(room.owner_id)
                room_dict['owner_name'] = owner.username if owner else '未知'
            else:
                room_dict['owner_name'] = '系统'
            rooms_data.append(room_dict)
        
        return jsonify({'rooms': rooms_data})
    
    except Exception as e:
        return jsonify({'error': f'获取聊天室列表失败: {str(e)}'}), 500

# 删除用户（管理员专用）
@app.route('/api/admin/delete_user', methods=['POST'])
def admin_delete_user():
    try:
        data = request.get_json()
        admin_id = data.get('admin_id')
        target_user_id = data.get('target_user_id')
        
        if not admin_id or not target_user_id:
            return jsonify({'error': '管理员ID和目标用户ID不能为空'}), 400
        
        admin = User.query.get(admin_id)
        if not admin or not admin.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        target_user = User.query.get(target_user_id)
        if not target_user:
            return jsonify({'error': '目标用户不存在'}), 404
        
        # 不能删除管理员账户
        if target_user.is_admin:
            return jsonify({'error': '不能删除管理员账户'}), 403
        
        # 删除用户拥有的聊天室（非总聊天室）
        owned_rooms = Room.query.filter_by(owner_id=target_user_id, is_main=False).all()
        for room in owned_rooms:
            db.session.delete(room)
        
        # 从所有聊天室中移除用户
        RoomMember.query.filter_by(user_id=target_user_id).delete()
        
        # 删除用户发送的所有消息
        Message.query.filter_by(user_id=target_user_id).delete()
        
        # 删除用户的所有邀请
        Invitation.query.filter((Invitation.sender_id == target_user_id) | (Invitation.receiver_id == target_user_id)).delete()
        
        # 删除用户账户
        db.session.delete(target_user)
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'用户 {target_user.username} 已被删除'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'删除用户失败: {str(e)}'}), 500

# 删除聊天室（管理员专用）
@app.route('/api/admin/delete_room', methods=['POST'])
def admin_delete_room():
    try:
        data = request.get_json()
        admin_id = data.get('admin_id')
        room_id = data.get('room_id')
        
        if not admin_id or not room_id:
            return jsonify({'error': '管理员ID和聊天室ID不能为空'}), 400
        
        admin = User.query.get(admin_id)
        if not admin or not admin.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'error': '聊天室不存在'}), 404
        
        # 不能删除总聊天室
        if room.is_main:
            return jsonify({'error': '不能删除总聊天室'}), 403
        
        room_name = room.name
        
        # 级联删除相关数据
        # 1. 删除聊天室消息
        Message.query.filter_by(room_id=room_id).delete()
        
        # 2. 删除聊天室成员关系
        RoomMember.query.filter_by(room_id=room_id).delete()
        
        # 3. 删除聊天室邀请
        Invitation.query.filter_by(room_id=room_id).delete()
        
        # 4. 删除聊天室本身
        db.session.delete(room)
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'聊天室 {room_name} 已被删除'})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'删除聊天室失败: {str(e)}'}), 500

# 清空聊天记录（管理员专用）
@app.route('/api/admin/clear_chat_history', methods=['POST'])
def admin_clear_chat_history():
    try:
        data = request.get_json()
        admin_id = data.get('admin_id')
        room_id = data.get('room_id')
        
        if not admin_id or not room_id:
            return jsonify({'error': '管理员ID和聊天室ID不能为空'}), 400
        
        admin = User.query.get(admin_id)
        if not admin or not admin.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'error': '聊天室不存在'}), 404
        
        room_name = room.name
        
        # 删除该聊天室的所有消息
        deleted_count = Message.query.filter_by(room_id=room_id).count()
        Message.query.filter_by(room_id=room_id).delete()
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'已清空聊天室 "{room_name}" 的 {deleted_count} 条聊天记录'
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'清空聊天记录失败: {str(e)}'}), 500

# 发送警告消息（管理员专用）
@app.route('/api/admin/send_warning', methods=['POST'])
def admin_send_warning():
    try:
        data = request.get_json()
        admin_id = data.get('admin_id')
        room_id = data.get('room_id')
        warning_message = data.get('warning_message', '').strip()
        
        if not admin_id or not room_id or not warning_message:
            return jsonify({'error': '管理员ID、聊天室ID和警告信息不能为空'}), 400
        
        admin = User.query.get(admin_id)
        if not admin or not admin.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'error': '聊天室不存在'}), 404
        
        # 创建警告消息
        warning_content = f"⚠️ 管理员警告: {warning_message}"
        message = Message(
            content=warning_content,
            message_type='warning',
            user_id=admin_id,
            room_id=room_id
        )
        db.session.add(message)
        db.session.commit()
        
        return jsonify({'success': True, 'message': '警告已发送'})
    
    except Exception as e:
        return jsonify({'error': f'发送警告失败: {str(e)}'}), 500

# 管理员加入任意聊天室
@app.route('/api/admin/join_room', methods=['POST'])
def admin_join_room():
    try:
        data = request.get_json()
        admin_id = data.get('admin_id')
        room_id = data.get('room_id')
        
        if not admin_id or not room_id:
            return jsonify({'error': '管理员ID和聊天室ID不能为空'}), 400
        
        admin = User.query.get(admin_id)
        if not admin or not admin.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        room = Room.query.get(room_id)
        if not room:
            return jsonify({'error': '聊天室不存在'}), 404
        
        # 检查是否已经是成员
        existing_member = RoomMember.query.filter_by(user_id=admin_id, room_id=room_id).first()
        if existing_member:
            return jsonify({'success': True, 'message': '您已经是该聊天室的成员'})
        
        # 加入聊天室
        room_member = RoomMember(user_id=admin_id, room_id=room_id)
        db.session.add(room_member)
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'已加入聊天室: {room.name}'})
    
    except Exception as e:
        return jsonify({'error': f'加入聊天室失败: {str(e)}'}), 500

# 检查用户状态（用于检测用户是否被删除）
@app.route('/api/user/status', methods=['GET'])
def check_user_status():
    try:
        user_id = request.args.get('user_id')
        
        if not user_id:
            return jsonify({'error': '用户ID不能为空'}), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'exists': False, 'message': '用户不存在'}), 200
        
        return jsonify({'exists': True, 'username': user.username}), 200
    
    except Exception as e:
        return jsonify({'error': f'检查用户状态失败: {str(e)}'}), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # 创建默认的总聊天室
        main_room = Room.query.filter_by(is_main=True).first()
        if not main_room:
            main_room = Room(name='总聊天室', is_main=True)
            db.session.add(main_room)
            db.session.commit()
        
        # 创建默认管理员账户
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin_user = User(username='admin', password='zzj20120111', is_admin=True)
            db.session.add(admin_user)
            db.session.commit()
            print("默认管理员账户已创建: admin/zzj20120111")
    
    app.run(debug=True, host='0.0.0.0', port=5001)
