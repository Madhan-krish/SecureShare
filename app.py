from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, send_file, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from cryptography.fernet import Fernet
from pymongo import MongoClient
import os
import datetime
import secrets
import boto3
import hashlib
import lzma
from bson.objectid import ObjectId
import re
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message


app = Flask(__name__)
app.secret_key = "secure_sharing_project" # Needed for login sessions
UPLOAD_FOLDER = 'uploads'
BIN_FOLDER = 'uploads/bin'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['BIN_FOLDER'] = BIN_FOLDER

socketio = SocketIO(app, cors_allowed_origins="*")

# --- STEP 1: MONGODB CONNECTION ---
MONGO_URI = "mongodb+srv://madhan_db_user:madhan-cloud@cluster0.cuxlmd1.mongodb.net/?appName=Cluster0&tlsAllowInvalidCertificates=true"

# Define global collections to avoid NameError if DB connection fails
db = None
users_collection = None
keys_collection = None
activities_collection = None
chats_collection = None
files_collection = None
requests_collection = None
otp_collection = None

try:
    client = MongoClient(
        MONGO_URI,
        tls=True,
        tlsAllowInvalidCertificates=True,  
        serverSelectionTimeoutMS=5000      
    )
    db = client['SecureShareDB']
    users_collection = db['users']
    keys_collection = db['keys']
    activities_collection = db['activities']
    chats_collection = db['chats']
    files_collection = db['files']
    requests_collection = db['requests']
    otp_collection = db['otp_verification']
    client.admin.command('ping') 
    print("SUCCESS: Connected to MongoDB Atlas with SSL Bypass!")
except Exception as e:
    print(f"ERROR: Database connection failed: {e}")

from dotenv import load_dotenv
load_dotenv()

# --- AWS S3 SETUP ---
AWS_ACCESS_KEY = os.environ.get('AWS_ACCESS_KEY')
AWS_SECRET_KEY = os.environ.get('AWS_SECRET_KEY')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'bucket-name')

try:
    s3_client = boto3.client(
        's3',
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION
    )
    print("SUCCESS: Configured AWS S3 Client with .env credentials.")
except Exception as e:
    print(f"WARNING: Could not configure boto3 S3 client: {e}")

# --- FLASK MAIL SETUP ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'secureshare01@gmail.com'
app.config['MAIL_PASSWORD'] = 'ukcnbjprewevrwnb'
app.config['MAIL_DEFAULT_SENDER'] = 'secureshare01@gmail.com'
mail = Mail(app)

# --- STEP 2: LOGGING & ENCRYPTION SETUP ---
def log_activity(member_email, action_type, filename=None, storage_saved=None, owner_email=None):
    if not member_email: return
    
    # Try to resolve owner_email if not provided
    if not owner_email:
        user = users_collection.find_one({"email": member_email})
        if user:
            owner_email = user.get('owner_email') or user.get('email') # Fallback if owner
            
    activity = {
        "member_email": member_email,
        "owner_email": owner_email,
        "action_type": action_type,
        "filename": filename,
        "timestamp": datetime.datetime.now()
    }
    if storage_saved is not None:
        activity["storage_saved_percent"] = storage_saved
    activities_collection.insert_one(activity)

def get_active_cipher():
    key_doc = keys_collection.find_one({"active": True})
    if key_doc:
        return Fernet(key_doc['key'].encode('utf-8'))
    else:
        new_key = Fernet.generate_key()
        keys_collection.insert_one({"key": new_key.decode('utf-8'), "active": True})
        return Fernet(new_key)

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

if not os.path.exists(BIN_FOLDER):
    os.makedirs(BIN_FOLDER)

# --- 30-DAY AUTO-CLEANUP FUNCTION ---
def cleanup_bin():
    if not os.path.exists(app.config['BIN_FOLDER']):
        return
    
    current_time = datetime.datetime.now().timestamp()
    thirty_days_seconds = 30 * 24 * 60 * 60 # 2,592,000 seconds
    
    for root, dirs, files in os.walk(app.config['BIN_FOLDER']):
        for f in files:
            file_path = os.path.join(root, f)
            if os.path.isfile(file_path):
                stat = os.stat(file_path)
                # If current time - modified time > 30 days
                if current_time - stat.st_mtime > thirty_days_seconds:
                    try:
                        os.remove(file_path)
                        print(f"AUTO-CLEANUP: Permanently deleted {f} (older than 30 days)")
                    except Exception as e:
                        print(f"Error auto-deleting {f}: {e}")

# --- STEP 3: WEB ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/handle_register', methods=['POST'])
def handle_register():
    username = request.form.get('username')
    email = request.form.get('email')
    phone = request.form.get('phone')
    role = request.form.get('role')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')

    if password != confirm_password:
        return jsonify({"status": "error", "message": "Passwords do not match."}), 400
        
    if len(password) < 8 or not re.search(r'\d', password) or not re.search(r'[^a-zA-Z0-9]', password):
        return jsonify({"status": "error", "message": "Password does not meet requirements."}), 400

    hashed_password = generate_password_hash(password)

    user_data = {
        "username": username,
        "email": email,
        "phone": phone,
        "role": role,
        "password": hashed_password, 
        "team_key": secrets.token_hex(4).upper() if role == 'owner' else ""
    }

    try:
        existing_user = users_collection.find_one({"email": email})
        if existing_user:
            return jsonify({"status": "error", "message": "Email already registered."}), 400
            
        existing_phone = users_collection.find_one({"phone": phone})
        if existing_phone:
            return jsonify({"status": "error", "message": "This mobile number is already linked to another account."}), 400
            
        # Generate 6 digit OTP
        otp = str(secrets.randbelow(1000000)).zfill(6)
        expires_at = datetime.datetime.now() + datetime.timedelta(minutes=5)
        
        # Store in OTP collection temporarily
        otp_collection.delete_many({"email": email}) # Clear any existing OTPs for email
        otp_collection.insert_one({
            "email": email,
            "otp": otp,
            "type": "register",
            "user_data": user_data,
            "expires_at": expires_at
        })
        
        # Send OTP Email
        try:
            msg = Message("SecureShare Registration OTP", recipients=[email])
            msg.body = f"Hello {username},\n\nYour OTP for SecureShare registration is: {otp}\n\nThis code will expire in 5 minutes.\n\nThank you,\nSecureShare Team"
            mail.send(msg)
            return jsonify({"status": "success", "message": "OTP sent"})
        except Exception as e:
            return jsonify({"status": "error", "message": "Failed to send OTP email."}), 500
        
    except Exception as e:
        return jsonify({"status": "error", "message": f"Database Error: {e}"}), 500

@app.route('/verify-otp')
def verify_otp_page():
    email = request.args.get('email')
    type = request.args.get('type')
    if not email or not type:
        return redirect(url_for('register_page'))
    return render_template('verify_otp.html', email=email, type=type)

@app.route('/verify-otp', methods=['POST'])
def verify_otp_json():
    email = request.form.get('email')
    entered_otp = request.form.get('otp')
    type = 'register'
    
    otp_record = otp_collection.find_one({"email": email, "type": type})
    
    if not otp_record:
        return jsonify({"status": "error", "message": "No pending verification found."}), 400
        
    if datetime.datetime.now() > otp_record['expires_at']:
        otp_collection.delete_one({"_id": otp_record['_id']})
        return jsonify({"status": "error", "message": "OTP has expired. Please request a new one."}), 400
        
    if otp_record['otp'] != entered_otp:
        return jsonify({"status": "error", "message": "Incorrect OTP entered."}), 400
        
    user_data = otp_record.get('user_data')
    if not user_data:
        return jsonify({"status": "error", "message": "User data lost. Please register again."}), 400
        
    users_collection.insert_one(user_data)
    otp_collection.delete_many({"email": email, "type": type})
    
    # Auto-login the user
    role = user_data.get('role')
    if role == 'owner':
        session['user_email'] = email
        session['owner_email'] = email
        log_activity(email, 'Registered and Logged In')
        redirect_url = url_for('dashboard')
    elif role == 'member':
        session['user_email'] = email
        session['owner_email'] = user_data.get('owner_email', '')
        log_activity(email, 'Registered and Logged In')
        redirect_url = url_for('dashboard')
    elif role == 'auditor':
        session['user_email'] = email
        session['owner_email'] = ""
        log_activity(email, 'Registered and Logged In')
        redirect_url = url_for('tpa_dashboard')
    else:
        redirect_url = url_for('dashboard') # Fallback

    return jsonify({
        "status": "success", 
        "message": "Email Verified & Successfully Registered!",
        "redirect_url": redirect_url
    })

@app.route('/handle_verify_otp', methods=['POST'])
def handle_verify_otp():
    email = request.form.get('email')
    type = request.form.get('type')
    entered_otp = request.form.get('otp')
    
    otp_record = otp_collection.find_one({"email": email, "type": type})
    
    if not otp_record:
        flash("No pending verification found or OTP expired.", "error")
        return redirect(url_for('register_page'))
        
    if datetime.datetime.now() > otp_record['expires_at']:
        otp_collection.delete_one({"_id": otp_record['_id']})
        flash("OTP has expired. Please request a new one.", "error")
        return render_template('verify_otp.html', email=email, type=type)
        
    if otp_record['otp'] != entered_otp:
        flash("Incorrect OTP entered.", "error")
        return render_template('verify_otp.html', email=email, type=type)
        
    # OTP is correct
    if type == 'register':
        user_data = otp_record.get('user_data')
        if not user_data:
            flash("User data getting lost. Please register again.", "error")
            return redirect(url_for('register_page'))
            
        users_collection.insert_one(user_data)
        otp_collection.delete_many({"email": email})
        flash("Email Verified & Successfully Registered! You can login now.", "success")
        return render_template('verify_otp.html', email=email, type='register', success_redirect=url_for('login_page'))
        
    elif type == 'forgot':
        # Valid OTP for password reset, set session flag to allow reset
        session['reset_email'] = email
        otp_collection.delete_many({"email": email})
        flash("OTP Verified. Please enter your new password.", "success")
        return render_template('verify_otp.html', email=email, type='forgot', success_redirect=url_for('reset_password'))

@app.route('/resend_otp', methods=['POST'])
def resend_otp():
    email = request.form.get('email')
    type = request.form.get('type')
    
    otp_record = otp_collection.find_one({"email": email, "type": type})
    if not otp_record:
        flash("No pending verification found.", "error")
        return redirect(url_for('register_page'))
        
    # Generate new OTP
    otp = str(secrets.randbelow(1000000)).zfill(6)
    expires_at = datetime.datetime.now() + datetime.timedelta(minutes=5)
    
    otp_collection.update_one({"_id": otp_record['_id']}, {"$set": {"otp": otp, "expires_at": expires_at}})
    
    username = otp_record.get('user_data', {}).get('username', 'User') if type == 'register' else 'User'
    
    try:
        msg = Message("SecureShare Resend OTP", recipients=[email])
        msg.body = f"Hello {username},\n\nYour new OTP for SecureShare is: {otp}\n\nThis code will expire in 5 minutes.\n\nThank you,\nSecureShare Team"
        mail.send(msg)
        flash("A new OTP has been sent to your email.", "success")
    except Exception as e:
        print(f"Mail error: {e}")
        flash("Failed to resend OTP email. Please check configuration.", "error")
        
    return render_template('verify_otp.html', email=email, type=type)

@app.route('/forgot_password', methods=['GET'])
def forgot_password():
    return render_template('forgot_password.html')

@app.route('/handle_forgot_password', methods=['POST'])
def handle_forgot_password():
    email = request.form.get('email')
    
    if users_collection is None:
        return jsonify({"status": "error", "message": "Database service is currently unavailable. Please try again later."}), 500
        
    user = users_collection.find_one({"email": email})
    
    if not user:
        return jsonify({
            "status": "success", 
            "message": "If this email is registered, an OTP has been sent.",
            "success_redirect": url_for('login_page')
        })
        
    otp = str(secrets.randbelow(1000000)).zfill(6)
    expires_at = datetime.datetime.now() + datetime.timedelta(minutes=5)
    
    otp_collection.delete_many({"email": email, "type": "forgot"})
    otp_collection.insert_one({
        "email": email,
        "otp": otp,
        "type": "forgot",
        "expires_at": expires_at
    })
    
    try:
        msg = Message("SecureShare Password Reset OTP", recipients=[email])
        msg.body = f"Hello {user.get('username', 'User')},\n\nYou requested a password reset. Your OTP is: {otp}\n\nThis code will expire in 5 minutes.\n\nThank you,\nSecureShare Team"
        mail.send(msg)
    except Exception as e:
        # Ignore mail send errors in this specific environment if it's already reaching the mailbox
        pass
        
    return jsonify({
        "status": "success", 
        "message": "OTP sent", 
        "success_redirect": url_for('verify_otp_page', email=email, type='forgot')
    })

@app.route('/reset_password', methods=['GET'])
def reset_password():
    email = session.get('reset_email')
    if not email:
        flash("Unauthorized request.", "error")
        return redirect(url_for('login_page'))
    return render_template('reset_password.html', email=email)

@app.route('/handle_reset_password', methods=['POST'])
def handle_reset_password():
    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    
    session_email = session.get('reset_email')
    if not session_email or session_email != email:
        flash("Unauthorized reset attempt.", "error")
        return redirect(url_for('login_page'))
        
    if password != confirm_password:
        flash("Passwords do not match! Please re-enter.", "error")
        return render_template('reset_password.html', email=email)
        
    if len(password) < 8 or not re.search(r'\d', password) or not re.search(r'[^a-zA-Z0-9]', password):
        flash("Password does not meet requirements.", "error")
        return render_template('reset_password.html', email=email)
        
    hashed_password = generate_password_hash(password)
    users_collection.update_many({"email": email}, {"$set": {"password": hashed_password}})
    
    session.pop('reset_email', None)
    
    flash("Password reset successfully! You can now login.", "success")
    return render_template('reset_password.html', email=email, success_redirect=url_for('login_page'))

@app.route('/handle_login', methods=['POST'])
def handle_login():
    role = request.form.get('role')
    email = request.form.get('email')
    password = request.form.get('password')

    user = users_collection.find_one({"email": email, "role": role})

    if user and (check_password_hash(user['password'], password) or user['password'] == password):
        if role == 'owner':
            session['user_email'] = email
            session['owner_email'] = email
            flash("Login Successful! Redirecting to Dashboard...", "success")
            return render_template('login.html', success_redirect=url_for('dashboard'))
        elif role == 'member':
            session['user_email'] = email
            session['owner_email'] = user.get('owner_email', '')
            log_activity(email, 'Logged In')
            flash("Login Successful! Redirecting to Dashboard...", "success")
            return render_template('login.html', success_redirect=url_for('dashboard'))
        elif role == 'auditor':
            session['user_email'] = email
            session['owner_email'] = ""
            log_activity(email, 'Logged In')
            flash("Login Successful! Redirecting to TPA Portal...", "success")
            return render_template('login.html', success_redirect=url_for('tpa_dashboard'))

    
    flash("Invalid Credentials or Password!", "error")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    
    user = users_collection.find_one({"email": session['user_email']})
    if not user:
        session.clear()
        return redirect(url_for('login_page'))
        
    owner_email = session.get('owner_email', '')
    if user.get('role') == 'member' and not owner_email:
        # Check if the member has since been assigned an owner
        if user.get('owner_email'):
            session['owner_email'] = user.get('owner_email')
            owner_email = user.get('owner_email')
    
    # Calculate Live Stats for Dashboard
    files_query = {"owner_email": owner_email, "source": "vault"}
    all_files = list(files_collection.find(files_query).sort("upload_date", -1))
    
    files_count = len(all_files)
    total_orig = sum(f.get('original_size', f.get('size', 0)) for f in all_files)
    total_comp = sum(f.get('compressed_encrypted_size', f.get('size', 0)) for f in all_files)
    
    if total_orig > 0:
        savings_pct = round(((total_orig - total_comp) / total_orig) * 100, 1)
    else:
        savings_pct = 0.0
        
    dashboard_files = []
    for f in all_files:
        orig_kb = f.get('original_size', f.get('size', 0)) / 1024
        comp_kb = f.get('compressed_encrypted_size', f.get('size', 0)) / 1024
        file_savings = round(((orig_kb - comp_kb) / orig_kb) * 100, 1) if orig_kb > 0 else 0
        mtime = f.get('upload_date', datetime.datetime.now()).strftime("%Y-%m-%d %H:%M")
        
        dashboard_files.append({
            'id': str(f['_id']),
            'Key': f['encrypted_name'],
            'filename': f['filename'],
            'Original': f"{orig_kb:.2f} KB",
            'Optimized': f"{comp_kb:.2f} KB",
            'Savings': f"{file_savings}%",
            'Date': mtime
        })
        
    # Get group members
    group_members = list(users_collection.find({"role": "member", "owner_email": owner_email}))
    members_count = len(group_members)
        
    owner = users_collection.find_one({"email": user.get('owner_email', '')})
    owner_display = owner.get('username') or owner.get('email') if owner else "Unknown Owner"
    
    # Get pending requests if owner
    pending_requests = []
    if user.get('role') == 'owner':
        p_reqs = list(requests_collection.find({"owner_email": user['email'], "status": "pending"}).sort("created_at", -1))
        for r in p_reqs:
            req_user = users_collection.find_one({"email": r['user_email']})
            if req_user:
                pending_requests.append({
                    'id': str(r['_id']),
                    'user_email': req_user.get('email', ''),
                    'username': req_user.get('username', 'Unknown')
                })

    # Fetch 5 Recent Activities for Notifications
    recent_activities = []
    if owner_email:
         activities = list(activities_collection.find({"owner_email": owner_email}).sort("timestamp", -1).limit(5))
         for act in activities:
             recent_activities.append({
                 "action_type": act.get("action_type"),
                 "member_email": act.get("member_email"),
                 "filename": act.get("filename"),
                 "timestamp": act.get("timestamp").strftime("%Y-%m-%d %H:%M") if 'timestamp' in act else "Unknown"
             })

    return render_template('dashboard.html', 
                           user=user, 
                           active_page='dashboard', 
                           files_count=files_count, 
                           savings_pct=savings_pct,
                           dashboard_files=dashboard_files,
                           group_members=group_members,
                           members_count=members_count,
                           owner_display=owner_display, 
                           team_key=user.get('team_key', ''),
                           pending_requests=pending_requests,
                           recent_activities=recent_activities)

@app.route('/members')
def members():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'owner':
        flash("Unauthorized Access", "error")
        return redirect(url_for('dashboard'))
        
    member_list = list(users_collection.find({"role": "member", "owner_email": session.get('user_email')}))
    return render_template('dashboard.html', user=user, members=member_list, active_page='members')


@app.route('/vault')
def vault():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    
    user = users_collection.find_one({"email": session['user_email']})
    
    owner_email = session.get('owner_email', '')
    
    vault_files = []
    try:
        v_files = files_collection.find({"owner_email": owner_email, "source": "vault"}).sort("upload_date", -1)
        for vf in v_files:
            orig_size_kb = vf.get('original_size', vf.get('size', 0)) / 1024
            comp_size_kb = vf.get('compressed_encrypted_size', vf.get('size', 0)) / 1024
            mtime = vf.get('upload_date', datetime.datetime.now()).strftime("%Y-%m-%d %H:%M")
            
            vault_files.append({
                'Key': vf.get('encrypted_name', ''),
                'LastModified': mtime,
                'OrigSize': f"{orig_size_kb:.2f} KB",
                'CompSize': f"{comp_size_kb:.2f} KB"
            })
    except Exception as e:
        print(f"Error fetching vault files: {e}")
        
    chat_files = []
    try:
        c_files = files_collection.find({"owner_email": owner_email, "source": "chat"})
        for cf in c_files:
            orig_size_kb = cf.get('original_size', cf.get('size', 0)) / 1024
            comp_size_kb = cf.get('compressed_encrypted_size', cf.get('size', 0)) / 1024
            mtime = cf.get('upload_date', datetime.datetime.now()).strftime("%Y-%m-%d %H:%M")
            chat_files.append({
                'id': str(cf['_id']),
                'filename': cf['filename'],
                'sender': cf.get('uploader_email', 'Unknown'),
                'channel': cf.get('channel_id', ''),
                'source_type': cf.get('source_type', 'chat'),
                'OrigSize': f"{orig_size_kb:.2f} KB",
                'CompSize': f"{comp_size_kb:.2f} KB",
                'LastModified': mtime
            })
    except Exception as e:
        print(f"Error fetching chat files: {e}")

    return render_template('dashboard.html', user=user, vault_files=vault_files, chat_files=chat_files, active_page='vault')

@app.route('/upload', methods=['POST'])
def upload_file():
    cipher_suite = get_active_cipher()
    if 'myFile' not in request.files:
        flash("No file part", "error")
        return redirect(url_for('dashboard'))
    
    file = request.files['myFile']
    if file.filename == '':
        flash("No selected file", "error")
        return redirect(url_for('dashboard'))

    try:
        file_data = file.read()
        # EXTREME COMPRESSION: LZMA preset 9
        compressed_data = lzma.compress(file_data, preset=9)
        encrypted_data = cipher_suite.encrypt(compressed_data)
        
        orig_len = len(file_data)
        enc_len = len(encrypted_data)
        saved_pct = ((orig_len - enc_len) / orig_len * 100) if orig_len > 0 else 0
        
        file_hash = hashlib.sha256(encrypted_data).hexdigest()
        
        file_name = f"{file.filename}.enc"
        
        owner_email = session.get('owner_email', '')
        s3_key = f"vault_files/{owner_email}/{file_name}"
        
        print(f"Uploading {file.filename} to S3...")
        try:
            # Upload directly to AWS S3
            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=s3_key,
                Body=encrypted_data
            )
        except Exception as e:
            print(str(e))
            raise e
            
        user_email = session.get('user_email', '')
        
        file_doc = {
            "filename": file.filename,
            "encrypted_name": file_name,
            "s3_key": s3_key,
            "owner_email": owner_email,
            "uploader_email": user_email,
            "source": "vault",
            "upload_date": datetime.datetime.now(),
            "original_size": len(file_data),
            "compressed_encrypted_size": len(encrypted_data),
            "size": len(file_data), # Legacy fallback
            "file_hash": file_hash
        }
        files_collection.insert_one(file_doc)
        
        if user_email and user_email != owner_email:
            log_activity(user_email, 'Uploaded File', file.filename, storage_saved=saved_pct)
            
        flash(f"Success! '{file.filename}' securely encrypted and saved locally.", "success")
        
    except Exception as e:
        flash(f"Upload failed: {str(e)}", "error")

    return redirect(url_for('vault'))

@app.route('/chat_upload', methods=['POST'])
def chat_upload():
    if 'user_email' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    cipher_suite = get_active_cipher()
    
    if 'myFile' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['myFile']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    channel_id = request.form.get('channel_id')
    if not channel_id:
        return jsonify({"error": "Missing channel_id"}), 400

    try:
        user_email = session.get('user_email')
        owner_email = session.get('owner_email')
        
        file_data = file.read()
        # EXTREME COMPRESSION: LZMA preset 9
        compressed_data = lzma.compress(file_data, preset=9)
        encrypted_data = cipher_suite.encrypt(compressed_data)
        
        orig_len = len(file_data)
        enc_len = len(encrypted_data)
        saved_pct = ((orig_len - enc_len) / orig_len * 100) if orig_len > 0 else 0
        
        file_hash = hashlib.sha256(encrypted_data).hexdigest()
        
        file_name = f"{secrets.token_hex(8)}_{file.filename}.enc"
        s3_key = f"chat_shared_files/{file_name}"
        
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=encrypted_data
        )
        
        file_doc = {
            "filename": file.filename,
            "encrypted_name": file_name,
            "s3_key": s3_key,
            "owner_email": owner_email,
            "uploader_email": user_email,
            "channel_id": channel_id,
            "source": "chat",
            "source_type": "local_upload",
            "upload_date": datetime.datetime.now(),
            "original_size": len(file_data),
            "compressed_encrypted_size": len(encrypted_data),
            "size": len(file_data), # Legacy fallback
            "file_hash": file_hash
        }
        inserted = files_collection.insert_one(file_doc)
        file_id = str(inserted.inserted_id)
        
        log_activity(user_email, 'Uploaded Chat File', file.filename, storage_saved=saved_pct)
        
        user = users_collection.find_one({"email": user_email})
        sender_name = user['username'] if user else "Unknown"
        
        socketio.emit('file_shared', {
            'sender_name': sender_name,
            'filename': file.filename,
            'channel_id': channel_id,
            'file_id': file_id
        }, room=channel_id)
        
        return jsonify({"success": True, "file_id": file_id, "filename": file.filename})
        
    except Exception as e:
        print(f"Chat Upload Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/download_chat/<file_id>')
def download_chat_file(file_id):
    cipher_suite = get_active_cipher()
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
        
    try:
        file_doc = files_collection.find_one({"_id": ObjectId(file_id)})
        if not file_doc:
            flash("File not found in database!", "error")
            return redirect(url_for('vault'))
            
        original_name = file_doc['filename']
        
        # Download from S3
        response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=file_doc['s3_key'])
        encrypted_data = response['Body'].read()

        # Decrypt
        decrypted_data = cipher_suite.decrypt(encrypted_data)
        
        # Decompress with backward compatibility (LZMA -> ZLIB -> UNCOMPRESSED)
        try:
            original_data = lzma.decompress(decrypted_data)
        except lzma.LZMAError:
            try:
                original_data = zlib.decompress(decrypted_data)
            except zlib.error:
                # Fallback for old encrypted files that were not compressed
                original_data = decrypted_data
        
        user_email = session.get('user_email', '')
        owner_email = session.get('owner_email', '')
        if user_email and user_email != owner_email:
            log_activity(user_email, 'Downloaded Chat File', original_name)
        
        import io
        return send_file(
            io.BytesIO(original_data),
            as_attachment=True,
            download_name=original_name,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        print(f"Decryption or Download Error: {e}")
        flash(f"Download Error: {e}", "error")
        return redirect(url_for('vault'))

@app.route('/api/my_vault_files')
def api_my_vault_files():
    if 'user_email' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    owner_email = session.get('owner_email')
    user_email = session.get('user_email')
    
    # Get files the user has access to share
    files = list(files_collection.find({"owner_email": owner_email, "source": "vault"}))
    
    result = []
    for f in files:
        orig_kb = f.get('original_size', f.get('size', 0)) / 1024
        comp_kb = f.get('compressed_encrypted_size', f.get('size', 0)) / 1024
        result.append({
            'id': str(f['_id']),
            'filename': f['filename'],
            'orig_size': f"{orig_kb:.2f} KB",
            'comp_size': f"{comp_kb:.2f} KB",
            'date': f.get('upload_date', datetime.datetime.now()).strftime("%Y-%m-%d %H:%M")
        })
    return jsonify(result)

@app.route('/share_vault_file', methods=['POST'])
def share_vault_file():
    if 'user_email' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.json
    file_id = data.get('file_id')
    channel_id = data.get('channel_id')
    
    if not file_id or not channel_id:
        return jsonify({"error": "Missing parameters"}), 400
        
    try:
        user_email = session.get('user_email')
        owner_email = session.get('owner_email')
        
        orig_file = files_collection.find_one({"_id": ObjectId(file_id), "owner_email": owner_email})
        if not orig_file:
            return jsonify({"error": "File not found"}), 404
            
        shared_doc = {
            "filename": orig_file['filename'],
            "encrypted_name": orig_file['encrypted_name'],
            "path": orig_file.get('path'),
            "s3_key": orig_file.get('s3_key'),
            "owner_email": owner_email,
            "uploader_email": user_email,
            "channel_id": channel_id,
            "source": "chat",
            "source_type": "vault_shared",
            "upload_date": datetime.datetime.now(),
            "size": orig_file.get('size', 0)
        }
        inserted = files_collection.insert_one(shared_doc)
        new_file_id = str(inserted.inserted_id)
        
        log_activity(user_email, 'Shared Vault File', orig_file['filename'])
        
        user = users_collection.find_one({"email": user_email})
        sender_name = user['username'] if user else "Unknown"
        
        socketio.emit('file_shared', {
            'sender_name': sender_name,
            'filename': orig_file['filename'],
            'channel_id': channel_id,
            'file_id': new_file_id
        }, room=channel_id)
        
        return jsonify({"success": True, "file_id": new_file_id, "filename": orig_file['filename']})
        
    except Exception as e:
        print(f"Share Vault File Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/download/<path:filename>')
def download_file(filename):
    cipher_suite = get_active_cipher()
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
        
    try:
        owner_email = session.get('owner_email', '')
        f_doc = files_collection.find_one({"encrypted_name": filename, "owner_email": owner_email})
        encrypted_data = None
        
        if f_doc and f_doc.get('s3_key'):
            try:
                response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=f_doc['s3_key'])
                encrypted_data = response['Body'].read()
            except Exception as e:
                print(f"S3 fetch error: {e}")
                flash("File not found in Secure Cloud.", "error")
                return redirect(url_for('vault'))
        else:
            owner_folder = os.path.join(app.config['UPLOAD_FOLDER'], owner_email) if owner_email else app.config['UPLOAD_FOLDER']
            file_path = os.path.join(owner_folder, filename)
            if not os.path.exists(file_path):
                flash("File not found locally!", "error")
                return redirect(url_for('vault'))
                
            with open(file_path, 'rb') as f:
                encrypted_data = f.read()
        
        # Decrypt
        decrypted_data = cipher_suite.decrypt(encrypted_data)
        
        # Decompress with backward compatibility (LZMA -> ZLIB -> UNCOMPRESSED)
        try:
            original_data = lzma.decompress(decrypted_data)
        except lzma.LZMAError:
            try:
                original_data = zlib.decompress(decrypted_data)
            except zlib.error:
                original_data = decrypted_data
        
        # Original name
        original_name = filename.replace('.enc', '') if filename.endswith('.enc') else filename
        
        user_email = session.get('user_email', '')
        owner_email = session.get('owner_email', '')
        if user_email and user_email != owner_email:
            log_activity(user_email, 'Downloaded File', original_name)
        
        import io
        return send_file(
            io.BytesIO(original_data),
            as_attachment=True,
            download_name=original_name,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        print(f"Decryption or Download Error: {e}")
        flash(f"Decryption Error: The file might have been encrypted with a revoked key.", "error")
        return redirect(url_for('vault'))

@app.route('/view/<path:filename>')
def view_file(filename):
    cipher_suite = get_active_cipher()
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
        
    try:
        owner_email = session.get('owner_email', '')
        f_doc = files_collection.find_one({"encrypted_name": filename, "owner_email": owner_email})
        encrypted_data = None
        
        if f_doc and f_doc.get('s3_key'):
            try:
                response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=f_doc['s3_key'])
                encrypted_data = response['Body'].read()
            except Exception as e:
                print(f"S3 fetch error: {e}")
                flash("File not found in Secure Cloud.", "error")
                return redirect(url_for('vault'))
        else:
            owner_folder = os.path.join(app.config['UPLOAD_FOLDER'], owner_email) if owner_email else app.config['UPLOAD_FOLDER']
            file_path = os.path.join(owner_folder, filename)
            if not os.path.exists(file_path):
                flash("File not found locally!", "error")
                return redirect(url_for('vault'))
                
            with open(file_path, 'rb') as f:
                encrypted_data = f.read()
        
        decrypted_data = cipher_suite.decrypt(encrypted_data)
        
        # Decompress with backward compatibility (LZMA -> ZLIB -> UNCOMPRESSED)
        try:
            original_data = lzma.decompress(decrypted_data)
        except lzma.LZMAError:
            try:
                original_data = zlib.decompress(decrypted_data)
            except zlib.error:
                original_data = decrypted_data
        
        import mimetypes
        original_name = filename.replace('.enc', '') if filename.endswith('.enc') else filename
        content_type, _ = mimetypes.guess_type(original_name)
        if not content_type:
            content_type = 'application/octet-stream'
            
        # Check if file is natively viewable in a browser
        is_viewable = content_type.startswith('text/') or content_type.startswith('image/') or content_type in ['application/pdf', 'application/json']
        
        if not is_viewable:
            from flask import render_template_string
            ext = original_name.split('.')[-1].upper() if '.' in original_name else 'Unknown'
            return render_template_string("""
                <html><head><title>Format Not Supported</title><style>
                body { font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background-color: #f3f4f6; margin: 0; }
                .box { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); text-align: center; max-width: 500px; border-top: 5px solid #16a34a; }
                h1 { color: #1f2937; font-size: 24px; margin-bottom: 15px; }
                p { color: #4b5563; line-height: 1.5; margin-bottom: 25px; font-size: 15px; }
                </style></head>
                <body>
                <div class="box">
                    <h1 style="color:#16a34a">Format Not Supported</h1>
                    <p>Web browsers cannot natively preview <b>.{{ ext }}</b> files inline without downloading them to your machine.</p>
                    <p>To strictly enforce "View Only" functionality, this action has been blocked. Please close this tab and utilize the <b>Download</b> protocol if you wish to access this data.</p>
                </div>
                </body></html>
            """, ext=ext)
        
        import io
        user_email = session.get('user_email', '')
        owner_email = session.get('owner_email', '')
        if user_email and user_email != owner_email:
            log_activity(user_email, 'Viewed File', original_name)
            
        response = send_file(
            io.BytesIO(original_data),
            mimetype=content_type,
            as_attachment=False
        )
        response.headers["Content-Disposition"] = f"inline; filename={original_name}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    except Exception as e:
        flash(f"Decryption Error: Cannot view file. It may have been encrypted with a revoked key.", "error")
        return redirect(url_for('vault'))


@app.route('/rotate_key', methods=['POST'])
def rotate_key():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    user = users_collection.find_one({"email": session['user_email']})
    if user.get('role') != 'owner':
        flash("Unauthorized", "error")
        return redirect(url_for('dashboard'))
    
    keys_collection.update_many({"active": True}, {"$set": {"active": False}})
    new_key = Fernet.generate_key()
    keys_collection.insert_one({"key": new_key.decode('utf-8'), "active": True})
    
    flash("Encryption Key explicitly rotated.", "success")
    return redirect(url_for('dashboard'))

@app.route('/verify_owner', methods=['POST'])
def verify_owner():
    if 'user_email' not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'owner':
        return jsonify({"success": False, "error": "Unauthorized"}), 401
        
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Invalid JSON"}), 400
        
    password = data.get('password', '')
    
    from werkzeug.security import check_password_hash
    
    is_valid = False
    try:
        is_valid = check_password_hash(user['password'], password)
    except Exception:
        pass
        
    if not is_valid and user.get('password') == password:
        is_valid = True
        
    if is_valid:
        return jsonify({"success": True, "team_key": user.get('team_key', '')})
    else:
        log_activity(session['user_email'], 'Unauthorized/Failed Team Key Access Attempt')
        return jsonify({"success": False, "error": "Incorrect password"}), 403

# --- RECYCLE BIN ROUTES ---

@app.route('/bin')
def view_bin():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    
    user = users_collection.find_one({"email": session['user_email']})
    
    # Run auto-cleanup every time the bin is viewed
    cleanup_bin()
    
    bin_files = []
    owner_email = session.get('owner_email', '')
    owner_bin_folder = os.path.join(app.config['BIN_FOLDER'], owner_email) if owner_email else app.config['BIN_FOLDER']
    
    if os.path.exists(owner_bin_folder):
        files = os.listdir(owner_bin_folder)
        current_time = datetime.datetime.now().timestamp()
        
        for f in files:
            file_path = os.path.join(owner_bin_folder, f)
            if os.path.isfile(file_path):
                stat = os.stat(file_path)
                mtime = stat.st_mtime
                mtime_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                size_kb = stat.st_size / 1024
                
                # Calculate days remaining
                seconds_passed = current_time - mtime
                days_passed = int(seconds_passed / (24 * 3600))
                days_remaining = max(0, 30 - days_passed)
                
                bin_files.append({
                    'Key': f,
                    'DeletedOn': mtime_str,
                    'Size': f"{size_kb:.2f} KB",
                    'DaysRemaining': days_remaining
                })
        
    return render_template('dashboard.html', user=user, bin_files=bin_files, active_page='bin')

@app.route('/request_join', methods=['POST'])
def request_join():
    if 'user_email' not in session:
         return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    invitation_code = data.get('invitation_code')
    if not invitation_code:
         return jsonify({"error": "Missing invitation code"}), 400
         
    owner = users_collection.find_one({"role": "owner", "team_key": invitation_code})
    if not owner:
         return jsonify({"error": "Invalid invitation code"}), 404
         
    user_email = session['user_email']
    
    existing_req = requests_collection.find_one({"user_email": user_email, "owner_email": owner['email'], "status": "pending"})
    if existing_req:
         return jsonify({"error": "Request already pending for this group."}), 400
         
    request_doc = {
         "user_email": user_email,
         "owner_email": owner['email'],
         "status": "pending",
         "created_at": datetime.datetime.now()
    }
    requests_collection.insert_one(request_doc)
    
    # Notify Owner Real-Time
    user_doc = users_collection.find_one({"email": user_email})
    username_display = user_doc.get("username", user_email) if user_doc else user_email
    socketio.emit('new_join_request', {"message": f"New Join Request from {username_display}!"}, room=f"user_{owner['email']}")
    
    return jsonify({"success": True, "message": "Request sent to Owner. Please wait for approval."})

@app.route('/approve_request', methods=['POST'])
def approve_request():
    if 'user_email' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'owner':
        return jsonify({"error": "Unauthorized"}), 403
        
    data = request.json
    request_id = data.get('request_id')
    approve = data.get('approve', True)
    
    req_doc = requests_collection.find_one({"_id": ObjectId(request_id), "owner_email": user['email'], "status": "pending"})
    if not req_doc:
        return jsonify({"error": "Request not found"}), 404
        
    if approve:
        users_collection.update_one(
            {"email": req_doc['user_email']},
            {"$set": {"owner_email": user['email'], "team_key": user.get('team_key', '')}}
        )
        requests_collection.update_one({"_id": ObjectId(request_id)}, {"$set": {"status": "approved"}})
        
        # Recalculate member count and broadcast
        total_members = users_collection.count_documents({"role": "member", "owner_email": user['email']})
        socketio.emit('member_count_updated', {'new_count': total_members}, room=f"group_{user['email']}")
        socketio.emit('member_count_updated', {'new_count': total_members}, room=f"user_{user['email']}") # Emit directly to owner as well
        
        socketio.emit('approval_status', {"status": "approved", "owner_email": user['email']}, room=f"user_{req_doc['user_email']}")
        
        return jsonify({"success": True})
    else:
        requests_collection.update_one({"_id": ObjectId(request_id)}, {"$set": {"status": "denied"}})
        socketio.emit('approval_status', {"status": "denied"}, room=f"user_{req_doc['user_email']}")
        return jsonify({"success": True})

@socketio.on('join_user_room')
def on_join_user_room(data):
    if 'user_email' in data:
        join_room(f"user_{data['user_email']}")

@app.route('/move_to_bin/<path:filename>')
def move_to_bin(filename):
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
        
    try:
        owner_email = session.get('owner_email', '')
        owner_folder = os.path.join(app.config['UPLOAD_FOLDER'], owner_email) if owner_email else app.config['UPLOAD_FOLDER']
        owner_bin_folder = os.path.join(app.config['BIN_FOLDER'], owner_email) if owner_email else app.config['BIN_FOLDER']
        
        if not os.path.exists(owner_bin_folder):
            os.makedirs(owner_bin_folder)
            
        source_path = os.path.join(owner_folder, filename)
        dest_path = os.path.join(owner_bin_folder, filename)
        
        if os.path.exists(source_path):
            import shutil
            shutil.move(source_path, dest_path)
            # Update the modification time so the 30-day timer starts from when it entered the bin
            os.utime(dest_path, None) 
            flash(f"'{filename}' moved to Recycle Bin.", "success")
        else:
            flash("File not found!", "error")
            
    except Exception as e:
        flash(f"Error moving file: {e}", "error")
        
    return redirect(url_for('vault'))

@app.route('/delete_asset/<path:filename>')
def delete_asset(filename):
    if 'user_email' not in session:
         return redirect(url_for('login_page'))
    try:
         owner_email = session.get('owner_email', '')
         f_doc = files_collection.find_one({"encrypted_name": filename, "owner_email": owner_email})
         if f_doc:
             if f_doc.get('s3_key'):
                 try:
                     print(f"Deleting {filename} from S3...")
                     s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=f_doc['s3_key'])
                 except Exception as e:
                     print(f"Error deleting from S3: {str(e)}")
             files_collection.delete_one({"_id": f_doc["_id"]})
             
             # Also ensure we check legacy local
             owner_folder = os.path.join(app.config['UPLOAD_FOLDER'], owner_email) if owner_email else app.config['UPLOAD_FOLDER']
             file_path = os.path.join(owner_folder, filename)
             if os.path.exists(file_path):
                 os.remove(file_path)
                 
             flash(f"'{filename}' has been successfully deleted from all secure systems.", "success")
         else:
             flash("File not found!", "error")
    except Exception as e:
         flash(f"Error dropping file: {e}", "error")
    return redirect(url_for('dashboard'))

@app.route('/delete_bulk', methods=['POST'])
def delete_bulk():
    if 'user_email' not in session:
        return jsonify({"error": "Unauthorized"}), 401
        
    data = request.json
    file_ids = data.get('file_ids', [])
    if not file_ids:
        return jsonify({"error": "No files selected"}), 400
        
    owner_email = session.get('owner_email', '')
    
    deleted_count = 0
    for fid in file_ids:
        try:
            f_doc = files_collection.find_one({"_id": ObjectId(fid), "owner_email": owner_email})
            if f_doc:
                if f_doc.get('s3_key'):
                    try:
                        print(f"Bulk Deleting {f_doc.get('filename')} from S3...")
                        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=f_doc['s3_key'])
                    except Exception as e:
                        # Proceed with Mongo deletion even if S3 fails
                        print(f"Error deleting {f_doc.get('filename')} from S3: {str(e)}")
                
                files_collection.delete_one({"_id": f_doc["_id"]})
                
                # Legacy local cleanup
                owner_folder = os.path.join(app.config['UPLOAD_FOLDER'], owner_email) if owner_email else app.config['UPLOAD_FOLDER']
                file_path = os.path.join(owner_folder, f_doc.get('encrypted_name', ''))
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except:
                        pass
                
                deleted_count += 1
        except Exception as e:
            print(f"Error processing deletion for id {fid}: {e}")
            
    return jsonify({"success": True, "deleted": deleted_count})

@app.route('/restore/<path:filename>')
def restore_file(filename):
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
        
    try:
        owner_email = session.get('owner_email', '')
        owner_folder = os.path.join(app.config['UPLOAD_FOLDER'], owner_email) if owner_email else app.config['UPLOAD_FOLDER']
        owner_bin_folder = os.path.join(app.config['BIN_FOLDER'], owner_email) if owner_email else app.config['BIN_FOLDER']
        
        if not os.path.exists(owner_folder):
            os.makedirs(owner_folder)
            
        source_path = os.path.join(owner_bin_folder, filename)
        dest_path = os.path.join(owner_folder, filename)
        
        if os.path.exists(source_path):
            import shutil
            shutil.move(source_path, dest_path)
            flash(f"'{filename}' successfully restored to the Vault.", "success")
        else:
            flash("File not found in bin!", "error")
            
    except Exception as e:
        flash(f"Error restoring file: {e}", "error")
        
    return redirect(url_for('view_bin'))

@app.route('/delete_permanent/<path:filename>')
def delete_permanent(filename):
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
        
    try:
        owner_email = session.get('owner_email', '')
        owner_bin_folder = os.path.join(app.config['BIN_FOLDER'], owner_email) if owner_email else app.config['BIN_FOLDER']
        
        file_path = os.path.join(owner_bin_folder, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            flash(f"'{filename}' has been permanently eradicated.", "success")
        else:
            flash("File not found in bin!", "error")
    except Exception as e:
        flash(f"Error deleting file permanently: {e}", "error")
        
    return redirect(url_for('view_bin'))

# --------------------------

@app.route('/revoke_member/<email>', methods=['POST'])
def revoke_member(email):
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    user = users_collection.find_one({"email": session['user_email']})
    if user.get('role') != 'owner':
        flash("Unauthorized", "error")
        return redirect(url_for('dashboard'))
    
    users_collection.delete_one({"email": email})
    
    # Auto-rotate key
    keys_collection.update_many({"active": True}, {"$set": {"active": False}})
    new_encryption_key = Fernet.generate_key()
    keys_collection.insert_one({"key": new_encryption_key.decode('utf-8'), "active": True})
    
    # Dynamic Rekeying: Generate new unique team key for the group
    import uuid
    new_team_key = uuid.uuid4().hex
    owner_email = session['user_email']
    
    # Update Owner's key
    users_collection.update_one({"email": owner_email}, {"$set": {"team_key": new_team_key}})
    # Update active members' keys
    users_collection.update_many({"owner_email": owner_email, "role": "member"}, {"$set": {"team_key": new_team_key}})
    
    # Notify remaining active peers
    socketio.emit('key_rotated', {}, room=f"group_{owner_email}")
    
    flash(f"Member '{email}' revoked. Encryption Key and Dynamic Team Key auto-rotated.", "success")
    return redirect(url_for('members'))

@app.route('/leave_group', methods=['POST'])
def leave_group():
    if 'user_email' not in session:
         return redirect(url_for('login_page'))
         
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'member':
         flash("Only active members can leave a group.", "error")
         return redirect(url_for('dashboard'))
         
    owner_email = user.get('owner_email')
    user_email = user.get('email')
    
    # Clear Access: Do NOT delete from users_collection
    # Set the user's owner_email (group_id) and team_key to ""
    users_collection.update_one(
        {"email": user_email},
        {"$set": {"owner_email": "", "team_key": ""}}
    )
    
    if owner_email:
        # Dynamic Rekeying constraints
        import uuid
        new_team_key = uuid.uuid4().hex
        
        # Update owner
        users_collection.update_one({"email": owner_email}, {"$set": {"team_key": new_team_key}})
        # Update other active peers
        users_collection.update_many({"owner_email": owner_email, "role": "member"}, {"$set": {"team_key": new_team_key}})
        
        # Notify peers
        socketio.emit('key_rotated', {}, room=f"group_{owner_email}")
    
    session['owner_email'] = ""
    flash("You have successfully left the group. Access revoked.", "success")
    return redirect(url_for('dashboard'))

@app.route('/member_logs/<email>')
def member_logs(email):
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'owner':
        flash("Unauthorized Access", "error")
        return redirect(url_for('dashboard'))
        
    member = users_collection.find_one({"email": email, "role": "member", "owner_email": session['user_email']})
    if not member:
        flash("Member not found or does not belong to your group.", "error")
        return redirect(url_for('members'))
        
    logs = list(activities_collection.find({"member_email": email}).sort("timestamp", -1))
    
    for log in logs:
        if 'timestamp' in log:
            log['timestamp_str'] = log['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
            
    return render_template('dashboard.html', user=user, active_page='member_logs', member_email=email, logs_data=logs)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/tpa_dashboard')
def tpa_dashboard():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'auditor':
        flash("Unauthorized Access", "error")
        return redirect(url_for('dashboard'))
        
    pending_files = list(files_collection.find({"$or": [{"status": "Waiting"}, {"status": {"$exists": False}}]}).sort("upload_date", -1))
    verified_files = list(files_collection.find({"status": "Verified"}))
    
    pending_count = len(pending_files)
    verified_count = len(verified_files)
    alerts_count = len(list(activities_collection.find({"action_type": "Integrity Alert"})))
    
    dashboard_files = []
    for f in pending_files:
        orig_kb = f.get('original_size', f.get('size', 0)) / 1024
        mtime = f.get('upload_date', datetime.datetime.now()).strftime("%b %d, %Y")
        owner_email = f.get('owner_email', '')
        owner_name = owner_email.split('@')[0].upper() if owner_email else "UNKNOWN"
        dashboard_files.append({
            'id': str(f['_id']),
            'filename': f['filename'],
            'owner': owner_name,
            'size': f"{orig_kb/1024:.1f} MB" if orig_kb > 1024 else f"{orig_kb:.1f} KB",
            'date': mtime,
            'status': 'Waiting'
        })
        
    all_cloud_files = []
    all_files = list(files_collection.find())
    for f in all_files:
        all_cloud_files.append({
            'id': str(f['_id']),
            'filename': f['filename'],
            'owner_email': f.get('owner_email', 'Unknown')
        })
        
    recent_logs = list(activities_collection.find({"action_type": {"$in": ["Integrity Verified", "Integrity Alert"]}}).sort("timestamp", -1).limit(5))
    logs = []
    for log in recent_logs:
        logs.append({
            'status': 'VALIDATED' if log['action_type'] == 'Integrity Verified' else 'INTEGRITY GAP',
            'filename': log.get('filename', ''),
            'time': log['timestamp'].strftime("%H:%M") if 'timestamp' in log else ""
        })
        
    return render_template('tpa_dashboard.html', 
                            user=user,
                            active_page='Dashboard',
                            pending_count=pending_count,
                            verified_count=verified_count,
                            alerts_count=alerts_count,
                            dashboard_files=dashboard_files,
                            all_cloud_files=all_cloud_files,
                            logs=logs)

@app.route('/auditor/export_report')
def export_audit_report():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'auditor':
        flash("Unauthorized Access", "error")
        return redirect(url_for('dashboard'))
        
    import io
    import csv
    from flask import make_response
    
    # Fetch all records related to audits
    audit_logs = list(activities_collection.find({"action_type": {"$in": ["Integrity Verified", "Integrity Alert"]}}).sort("timestamp", -1))
    
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["File Name", "Owner Email", "Audit Result", "Timestamp"])
    
    for log in audit_logs:
        result_text = 'VALIDATED' if log['action_type'] == 'Integrity Verified' else 'INTEGRITY GAP'
        cw.writerow([
            log.get('filename', 'N/A'),
            log.get('owner_email', 'N/A'),
            result_text,
            log['timestamp'].strftime("%Y-%m-%d %H:%M:%S") if 'timestamp' in log else "N/A"
        ])
        
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=Audit_Report.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/auditor/requests')
def auditor_requests():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'auditor':
        return redirect(url_for('dashboard'))
        
    all_files = list(files_collection.find().sort("upload_date", -1))
    requests_list = []
    for f in all_files:
        owner_email = f.get('owner_email', '')
        owner_name = owner_email.split('@')[0].upper() if owner_email else "UNKNOWN"
        mtime = f.get('upload_date', datetime.datetime.now()).strftime("%Y-%m-%d %H:%M")
        requests_list.append({
            'id': str(f['_id']),
            'filename': f['filename'],
            'owner': owner_name,
            'date': mtime
        })
        
    return render_template('audit_requests.html', user=user, active_page='Audit Requests', requests=requests_list)

@app.route('/auditor/verify')
def auditor_verify():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'auditor':
        return redirect(url_for('dashboard'))
        
    file_id = request.args.get('file_id', '')
    return render_template('integrity_check.html', user=user, active_page='Integrity Check', file_id=file_id)

@app.route('/auditor/logs')
def auditor_logs():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'auditor':
        return redirect(url_for('dashboard'))
        
    # Get only integrity related logs for TPA
    audit_logs = list(activities_collection.find({"action_type": {"$in": ["Integrity Verified", "Integrity Alert"]}}).sort("timestamp", -1))
    logs_list = []
    for log in audit_logs:
        logs_list.append({
            'filename': log.get('filename', 'Unknown'),
            'status': 'Verified' if log['action_type'] == 'Integrity Verified' else 'Tampered',
            'time': log['timestamp'].strftime("%Y-%m-%d %H:%M:%S") if 'timestamp' in log else ""
        })
        
    return render_template('audit_logs.html', user=user, active_page='Audit Logs', logs=logs_list)

@app.route('/auditor/settings')
def auditor_settings():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'auditor':
        return redirect(url_for('dashboard'))
        
    return render_template('auditor_settings.html', user=user, active_page='Settings')

@app.route('/api/verify_integrity', methods=['POST'])
def verify_integrity():
    if 'user_email' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'auditor':
        return jsonify({"error": "Unauthorized"}), 403
        
    data = request.json
    file_id = data.get('file_id')
    
    try:
        f_doc = files_collection.find_one({"_id": ObjectId(file_id)})
        if not f_doc:
            return jsonify({"error": "File not found"}), 404
            
        if not f_doc.get('s3_key'):
            return jsonify({"error": "File not verifiable on S3"}), 400
            
        # Fetch from S3
        response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=f_doc['s3_key'])
        s3_data = response['Body'].read()
        
        current_hash = hashlib.sha256(s3_data).hexdigest()
        original_hash = f_doc.get('file_hash')
        
        if current_hash == original_hash:
            files_collection.update_one({"_id": ObjectId(file_id)}, {"$set": {"status": "Verified"}})
            log_activity(session['user_email'], 'Integrity Verified', f_doc['filename'])
            return jsonify({"success": True, "message": "Verification Successful: Cloud data matches local block hashes."})
        else:
            files_collection.update_one({"_id": ObjectId(file_id)}, {"$set": {"status": "Compromised"}})
            log_activity(session['user_email'], 'Integrity Alert', f_doc['filename'])
            return jsonify({"success": False, "message": "Integrity Gap Detected: Cloud source data modified or corrupted!"})
            
    except Exception as e:
        print(f"Verify Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'admin':
        flash("Unauthorized Access", "error")
        return redirect(url_for('dashboard'))
        
    all_files = list(files_collection.find({}))
    total_size = sum(f.get('original_size', f.get('size', 0)) for f in all_files)
    
    # Active nodes = owners + members
    active_nodes = users_collection.count_documents({"role": {"$in": ["owner", "member"]}})
    
    # Storage Capacity calculation
    # Simulate a total capacity of 100 TB. Convert total_size (bytes) to TB.
    tb_used = total_size / (1024**4)
    if tb_used == 0 and total_size > 0:
        tb_used = total_size / (1024**2) # Display in MB if very small to show some number
        storage_display = f"{tb_used:.2f} MB"
    else:
        storage_display = f"{tb_used:.2f} TB"
        
    storage_pct = min((tb_used / 100.0) * 100, 100) if tb_used < 100 else 100
    if storage_pct == 0 and total_size > 0:
        storage_pct = 0.01 # minimal visual indication

    # Active groups
    groups = list(users_collection.find({"role": "owner"}))
    active_groups = []
    for g in groups:
        member_count = users_collection.count_documents({"owner_email": g['email'], "role": "member"})
        active_groups.append({
            'owner_email': g['email'],
            'owner_name': g.get('username', 'Unknown'),
            'member_count': member_count
        })

    # Master Activity Log
    recent_logs = list(activities_collection.find().sort("timestamp", -1).limit(50))
    logs = []
    for log in recent_logs:
        logs.append({
            'user': log.get('member_email', 'Unknown'),
            'action': log.get('action_type', ''),
            'resource': log.get('filename', 'System Auth/Keys'),
            'time': log['timestamp'].strftime("%Y-%m-%d %H:%M:%S") if 'timestamp' in log else ""
        })
        
    # Calculate Data Integrity Status roughly from failed files status
    compromised_files = files_collection.count_documents({"status": "Compromised"})
    integrity_status = "100% Verified" if compromised_files == 0 else f"{compromised_files} Compromised"
        
    return render_template('admin_dashboard.html',
                           user=user,
                           active_page='Dashboard',
                           active_nodes=active_nodes,
                           storage_display=storage_display,
                           storage_pct=storage_pct,
                           integrity_status=integrity_status,
                           active_groups=active_groups,
                           logs=logs)

@app.route('/admin/storage')
def admin_storage():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'admin':
        return redirect(url_for('dashboard'))
    return render_template('admin_storage.html', user=user, active_page='Storage')

@app.route('/admin/activity')
def admin_activity():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'admin':
        return redirect(url_for('dashboard'))
    return render_template('admin_activity.html', user=user, active_page='User Activity')

@app.route('/api/system_integrity_scan', methods=['POST'])
def system_integrity_scan():
    if 'user_email' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = users_collection.find_one({"email": session['user_email']})
    if not user or user.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
        
    try:
        all_verifiable_files = list(files_collection.find({"s3_key": {"$exists": True, "$ne": ""}}))
        
        checked = 0
        failed = 0
        
        for f_doc in all_verifiable_files:
            try:
                # Fetch from S3
                response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=f_doc['s3_key'])
                s3_data = response['Body'].read()
                
                current_hash = hashlib.sha256(s3_data).hexdigest()
                original_hash = f_doc.get('file_hash')
                
                if current_hash == original_hash:
                    files_collection.update_one({"_id": f_doc["_id"]}, {"$set": {"status": "Verified"}})
                else:
                    failed += 1
                    files_collection.update_one({"_id": f_doc["_id"]}, {"$set": {"status": "Compromised"}})
                    log_activity(session['user_email'], 'System Integrity Gap', f_doc['filename'])
                checked += 1
            except Exception as e:
                print(f"Error checking {f_doc.get('filename')}: {e}")
                # Can mark as failed if S3 object is missing
                failed += 1
                files_collection.update_one({"_id": f_doc["_id"]}, {"$set": {"status": "Missing/Compromised"}})
                
        log_activity(session['user_email'], 'System Integrity Scan', f'Checked {checked} files')
        
        return jsonify({
            "success": True, 
            "checked": checked, 
            "failed": failed,
            "message": f"Global scan complete. Checked {checked} files. Found {failed} anomalies."
        })
        
    except Exception as e:
        print(f"System Scan Error: {e}")
        return jsonify({"error": str(e)}), 500

# --- CHAT ROUTES & SOCKETS ---

online_users = {} # sid -> email

@socketio.on('connect')
def handle_connect():
    email = session.get('user_email')
    if email:
        online_users[request.sid] = email
        emit('status_change', {'email': email, 'status': 'online'}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    email = online_users.pop(request.sid, None)
    if email:
        # Check if user has other sessions alive
        if email not in online_users.values():
            emit('status_change', {'email': email, 'status': 'offline'}, broadcast=True)

@app.route('/chat')
def chat_page():
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
    
    user = users_collection.find_one({"email": session['user_email']})
    if not user:
        return redirect(url_for('login_page'))
    
    # Identify channels available
    channels = []
    
    # 1. Group Channel (Global to the team)
    team_key = user.get('team_key')
    owner_email = session.get('owner_email')
    
    channels.append({
        "id": f"group_{owner_email}",
        "name": "Group Channel",
        "type": "group",
        "is_online": True
    })
    
    online_emails = set(online_users.values())
    
    # 2. Private Channels
    if user.get('role') == 'owner':
        # Owner sees all members
        members = list(users_collection.find({"role": "member", "owner_email": session['user_email']}))
        for m in members:
            emails = sorted([session['user_email'], m['email']])
            channels.append({
                "id": f"private_{emails[0]}_{emails[1]}",
                "name": m['username'],
                "email": m['email'],
                "type": "private",
                "is_online": m['email'] in online_emails
            })
    else:
        # Member sees only Owner
        owner_doc = users_collection.find_one({"email": session.get('owner_email')})
        if owner_doc:
            owner_name = owner_doc['username']
            emails = sorted([session['user_email'], owner_email])
            channels.append({
                "id": f"private_{emails[0]}_{emails[1]}",
                "name": owner_name,
                "email": owner_email,
                "type": "private",
                "is_online": owner_email in online_emails
            })
        
    return render_template('dashboard.html', user=user, active_page='chat', channels=channels)

@app.route('/api/chat_history/<channel_id>')
def chat_history(channel_id):
    if 'user_email' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    messages = list(chats_collection.find({"channel_id": channel_id}).sort("timestamp", 1))
    for m in messages:
        m['_id'] = str(m['_id'])
        if 'timestamp' in m:
            m['timestamp_str'] = m['timestamp'].strftime("%H:%M")
    return jsonify(messages)

@socketio.on('join')
def on_join(data):
    room = data.get('room')
    if room:
        join_room(room)

@socketio.on('typing')
def handle_typing(data):
    room = data.get('room')
    is_typing = data.get('typing', False)
    email = session.get('user_email')
    if room and email:
        emit('user_typing', {'email': email, 'typing': is_typing, 'room': room}, room=room, include_self=False)

@socketio.on('send_message')
def handle_send_message(data):
    room = data['room']
    sender_email = session.get('user_email')
    user = users_collection.find_one({"email": sender_email})
    sender_name = user['username'] if user else "Unknown"
    
    receiver_id = None
    if room.startswith('private_'):
        parts = room.split('_')
        if len(parts) == 3:
            receiver_id = parts[1] if parts[2] == sender_email else parts[2]
            
    message = {
        "channel_id": room,
        "sender_email": sender_email,
        "sender_id": sender_email,
        "receiver_id": receiver_id,
        "sender_name": sender_name,
        "content": data['message'],
        "timestamp": datetime.datetime.now()
    }
    
    inserted = chats_collection.insert_one(message)
    message['_id'] = str(inserted.inserted_id)
    message['timestamp_str'] = message['timestamp'].strftime("%H:%M")
    
    emit('receive_message', message, room=room)

if __name__ == '__main__':
    socketio.run(app, debug=True)