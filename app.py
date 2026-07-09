from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import secrets

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(16))

# Database configuration
database_url = os.environ.get('DATABASE_URL')
if not database_url:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tasks.db'
else:
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

# ===== MODELS =====

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    tasks = db.relationship('Task', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default='Medium')
    status = db.Column(db.String(20), default='Pending')
    due_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===== CREATE TABLES =====
with app.app_context():
    db.create_all()

# ===== ROUTES =====

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not username or not email or not password:
            flash('All fields are required!', 'error')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('Passwords do not match!', 'error')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Password must be at least 6 characters!', 'error')
            return render_template('register.html')

        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered!', 'error')
            return render_template('register.html')

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False

        user = User.query.filter_by(username=username).first()

        if not user or not user.check_password(password):
            flash('Invalid username or password!', 'error')
            return render_template('login.html')

        login_user(user, remember=remember)
        flash('Welcome back, ' + user.username + '!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    total_tasks = Task.query.filter_by(user_id=current_user.id).count()
    pending_tasks = Task.query.filter_by(user_id=current_user.id, status='Pending').count()
    completed_tasks = Task.query.filter_by(user_id=current_user.id, status='Completed').count()
    
    recent_tasks = Task.query.filter_by(user_id=current_user.id).order_by(Task.created_at.desc()).limit(5).all()
    
    return render_template('dashboard.html',
                         total_tasks=total_tasks,
                         pending_tasks=pending_tasks,
                         completed_tasks=completed_tasks,
                         recent_tasks=recent_tasks)

@app.route('/tasks')
@login_required
def tasks():
    status = request.args.get('status', 'all')
    priority = request.args.get('priority', 'all')
    search = request.args.get('search', '')
    
    query = Task.query.filter_by(user_id=current_user.id)
    
    if status != 'all':
        query = query.filter_by(status=status)
    
    if priority != 'all':
        query = query.filter_by(priority=priority)
    
    if search:
        query = query.filter(Task.title.contains(search) | Task.description.contains(search))
    
    tasks_list = query.order_by(Task.created_at.desc()).all()
    
    return render_template('tasks.html', tasks=tasks_list, status=status, priority=priority, search=search)

@app.route('/add_task', methods=['GET', 'POST'])
@login_required
def add_task():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        priority = request.form.get('priority', 'Medium')
        due_date_str = request.form.get('due_date')
        
        if not title:
            flash('Task title is required!', 'error')
            return render_template('add_task.html')
        
        due_date = None
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
            except:
                flash('Invalid date format!', 'error')
                return render_template('add_task.html')
        
        task = Task(
            title=title,
            description=description,
            priority=priority,
            due_date=due_date,
            user_id=current_user.id
        )
        
        db.session.add(task)
        db.session.commit()
        
        flash('Task created successfully! ✅', 'success')
        return redirect(url_for('tasks'))
    
    return render_template('add_task.html')

@app.route('/edit_task/<int:task_id>', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    if task.user_id != current_user.id:
        flash('You do not have permission to edit this task.', 'error')
        return redirect(url_for('tasks'))
    
    if request.method == 'POST':
        task.title = request.form.get('title')
        task.description = request.form.get('description')
        task.priority = request.form.get('priority')
        task.status = request.form.get('status')
        due_date_str = request.form.get('due_date')
        
        if not task.title:
            flash('Task title is required!', 'error')
            return render_template('edit_task.html', task=task)
        
        if due_date_str:
            try:
                task.due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
            except:
                flash('Invalid date format!', 'error')
                return render_template('edit_task.html', task=task)
        else:
            task.due_date = None
        
        db.session.commit()
        flash('Task updated successfully! ✅', 'success')
        return redirect(url_for('tasks'))
    
    return render_template('edit_task.html', task=task)

@app.route('/delete_task/<int:task_id>')
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    if task.user_id != current_user.id:
        flash('You do not have permission to delete this task.', 'error')
        return redirect(url_for('tasks'))
    
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted successfully! 🗑️', 'success')
    return redirect(url_for('tasks'))

@app.route('/complete_task/<int:task_id>')
@login_required
def complete_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    if task.user_id != current_user.id:
        flash('You do not have permission to complete this task.', 'error')
        return redirect(url_for('tasks'))
    
    task.status = 'Completed'
    db.session.commit()
    flash('Task marked as completed! 🎉', 'success')
    return redirect(url_for('tasks'))

@app.route('/api/tasks')
@login_required
def api_tasks():
    tasks = Task.query.filter_by(user_id=current_user.id).all()
    return jsonify([{
        'id': t.id,
        'title': t.title,
        'status': t.status,
        'priority': t.priority,
        'due_date': t.due_date.strftime('%Y-%m-%d') if t.due_date else None
    } for t in tasks])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
