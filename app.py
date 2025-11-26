from flask import Flask, render_template, request, redirect, url_for, flash, session
from models import db, User, Test, Question, Option, Result
from sqlalchemy.orm import joinedload
from functools import wraps
import os
import random
import json
import config
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config.from_object(config)
db.init_app(app)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()

        if not user:
            flash('Для доступа к этой странице необходимо войти.', 'error')
            return redirect(url_for('login'))

        if not user.is_admin:
            flash('Доступ запрещен. Требуются права администратора.', 'error')
            return redirect(url_for('index'))

        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    user_id = session.get('user_id')
    if user_id:
        return db.session.get(User, user_id)
    return None


@app.route('/')
def index():
    try:
        all_tests = Test.query.all()
    except:
        all_tests = []

    current_user = get_current_user()

    return render_template('index.html', tests=all_tests, user=current_user)

@app.route('/profile')
def profile():
    current_user = get_current_user()
    
    if not current_user:
        flash('Пожалуйста, войдите, чтобы просмотреть ваш профиль.', 'error')
        return redirect(url_for('login'))
        
    user_results = Result.query.filter_by(user_id=current_user.id).order_by(Result.date_completed.desc()).all()
    
    return render_template('profile.html', user=current_user, results=user_results)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user_exists = User.query.filter_by(username=username).first()
        if user_exists:
            flash('Пользователь с таким именем уже существует.', 'error')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, password_hash=hashed_password, is_admin=False)
        db.session.add(new_user)
        db.session.commit()

        flash('Регистрация прошла успешно! Теперь вы можете войти.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            flash(f'Вы успешно вошли как {user.username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Неверное имя пользователя или пароль.', 'error')
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Вы вышли из системы.', 'success')
    return redirect(url_for('index'))




@app.route('/admin/test_results/<int:test_id>')
@admin_required
def test_results(test_id):
    test = Test.query.get_or_404(test_id)
    
    results = Result.query.filter_by(test_id=test_id).options(db.joinedload(Result.user)).order_by(Result.date_completed.desc()).all()
    
    total_questions = len(test.questions)
    
    return render_template('test_results.html',
                        test=test,
                        results=results,
                        total_questions=total_questions)

@app.route('/admin/create_test', methods=['GET', 'POST'])
@admin_required
def create_test():
    if request.method == 'POST':
        questions_to_process = {}
        
        print(f"\n--- Начало обработки POST-запроса ---")
        print(f"Форма содержит ключей: {len(request.form)}")
        
        for key, value in request.form.items():
            
            if key in ['title', 'description', 'test_difficulty']:
                continue

            parts = key.split('_')
            q_id = None
            
            if key.startswith('q_text_'):
                if len(parts) >= 3 and parts[-1].isdigit():
                    q_id = parts[-1]
            elif key.startswith('q_') and len(parts) >= 2 and parts[1].isdigit():
                q_id = parts[1]

            if q_id is None:
                continue 
            
            q_id = str(q_id) 

            if q_id not in questions_to_process:
                questions_to_process[q_id] = {'options': {}}
            
            if key.startswith('q_text_'):
                questions_to_process[q_id]['text'] = value
            
            elif key.endswith('_difficulty'):
                questions_to_process[q_id]['difficulty'] = value

            elif key.endswith('_time_limit'):
                try:
                    value = value.strip()
                    if value:
                        questions_to_process[q_id]['time_limit'] = int(value)
                except ValueError:
                    print(f"ОШИБКА 1: Неверный формат времени для вопроса {q_id}. Значение: '{value}'")
                    flash(f'Ошибка: Неверный формат времени для вопроса {q_id}.', 'error')
                    return redirect(url_for('create_test'))

            elif key.endswith('_correct'):
                questions_to_process[q_id]['correct_option_index'] = value
            
            elif '_option_text_' in key:
                o_index = parts[-1] 
                questions_to_process[q_id]['options'][o_index] = value

        print(f"Сырые данные вопросов: {questions_to_process}")
        title = request.form.get('title')
        description = request.form.get('description')
        test_difficulty = request.form.get('test_difficulty', 'Средний')
        
        valid_questions = {k: v for k, v in questions_to_process.items() if v.get('text', '').strip()}
        
        print(f"Действительных вопросов (с текстом): {len(valid_questions)}")
        
        if len(valid_questions) < 2:
            print("ОШИБКА 2: Меньше 2 вопросов с текстом. Прерывание.")
            flash('Невозможно создать тест: требуется минимум 2 вопроса с текстом.', 'error')
            return redirect(url_for('create_test'))

        new_test = Test(title=title, description=description, difficulty=test_difficulty)
        db.session.add(new_test)
        db.session.flush()

        try:
            questions_count = 0
            for q_id, q_data in valid_questions.items():
                
                if len(q_data.get('options', {})) < 2 or q_data.get('correct_option_index') is None:
                    print(f"ПРЕДУПРЕЖДЕНИЕ: Вопрос {q_id} пропущен из-за нехватки вариантов/ответа.")
                    flash(f'Вопрос {q_id} пропущен: нет минимума (2) вариантов или не указан правильный ответ.', 'warning')
                    continue
                    
                new_question = Question(
                    test_id=new_test.id, 
                    text=q_data.get('text'),
                    difficulty=q_data.get('difficulty', 'Средний'),
                    time_limit_sec=q_data.get('time_limit') if isinstance(q_data.get('time_limit'), int) else 60
                )
                db.session.add(new_question)
                db.session.flush() 
                questions_count += 1
                
                correct_option_index = str(q_data.get('correct_option_index'))
                
                for o_index, o_text in q_data['options'].items():
                    o_text = o_text.strip()
                    if not o_text:
                        continue 
                        
                    is_correct = (str(o_index) == correct_option_index)
                    
                    new_option = Option(
                        question_id=new_question.id, 
                        text=o_text, 
                        is_correct=is_correct
                    )
                    db.session.add(new_option)

            print(f"Финальное количество сохраненных вопросов: {questions_count}")
            
            if questions_count < 2:
                print("ОШИБКА 3: В базе сохранено меньше 2 вопросов. Откат транзакции.")
                db.session.rollback()
                flash('Тест отменен: в нем должно быть минимум 2 действительных вопроса.', 'error')
                return redirect(url_for('create_test'))

            db.session.commit()
            print(f"УСПЕХ: Тест '{title}' создан. Вопросов: {questions_count}")
            flash(f'Тест "{title}" успешно создан! Добавлено вопросов: {questions_count}', 'success')
            return redirect(url_for('index'))

        except Exception as e:
            db.session.rollback()
            print(f"\n--- КРИТИЧЕСКАЯ ОШИБКА БД: {e} ---")
            flash(f'Критическая ошибка при сохранении теста в БД. Подробности в логах сервера.', 'error')
            return redirect(url_for('create_test'))

    return render_template('create_test.html')

@app.route('/admin/delete_test/<int:test_id>', methods=['POST'])
@admin_required
def delete_test(test_id):
    test_to_delete = Test.query.get_or_404(test_id)
    test_title = test_to_delete.title

    try:
        Result.query.filter_by(test_id=test_id).delete()
        
        questions = Question.query.filter_by(test_id=test_id).all()
        question_ids = [q.id for q in questions]
        
        if question_ids:
            Option.query.filter(Option.question_id.in_(question_ids)).delete(synchronize_session=False)

        Question.query.filter_by(test_id=test_id).delete(synchronize_session=False)

        db.session.delete(test_to_delete)
        db.session.commit()
        
        flash(f'Тест "{test_title}" и все связанные данные успешно удалены.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении теста "{test_title}": {e}', 'error')
        
    return redirect(url_for('index'))

@app.route('/admin/import_test', methods=['POST'])
@admin_required
def import_test():
    if 'file' not in request.files:
        flash('Файл не был загружен.', 'error')
        return redirect(url_for('create_test'))

    file = request.files['file']
    if file.filename == '':
        flash('Файл не выбран.', 'error')
        return redirect(url_for('create_test'))

    if file and file.filename.endswith('.json'):
        try:
            json_data = json.load(file.stream)

            title = json_data.get('title')
            description = json_data.get('description')
            test_difficulty = json_data.get('difficulty', 'Средний')
            questions_data = json_data.get('questions')

            if not all([title, questions_data, isinstance(questions_data, list)]):
                flash('JSON имеет неверную структуру (отсутствует title или questions).', 'error')
                return redirect(url_for('create_test'))

            new_test = Test(title=title, description=description, difficulty=test_difficulty)
            db.session.add(new_test)
            db.session.flush()

            for q_data in questions_data:
                q_text = q_data.get('text')
                q_difficulty = q_data.get('difficulty', 'Средний')
                q_time = q_data.get('time_limit_sec', 60)
                options = q_data.get('options')
                correct_index = q_data.get('correct_option_index')

                if not all([q_text, options, correct_index is not None]):
                    raise ValueError(f"Вопрос '{q_text}' имеет неполные данные.")

                new_question = Question(
                    test_id=new_test.id, 
                    text=q_text,
                    difficulty=q_difficulty,
                    time_limit_sec=q_time
                )
                db.session.add(new_question)
                db.session.flush()

                for idx, o_text in enumerate(options):
                    is_correct = (idx == correct_index)
                    new_option = Option(
                        question_id=new_question.id, 
                        text=o_text, 
                        is_correct=is_correct
                    )
                    db.session.add(new_option)

            db.session.commit()
            flash(f'Тест "{title}" успешно импортирован!', 'success')
            return redirect(url_for('index'))

        except json.JSONDecodeError:
            db.session.rollback()
            flash('Ошибка: Не удалось прочитать JSON-файл.', 'error')
        except ValueError as e:
            db.session.rollback()
            flash(f'Ошибка в данных теста: {e}', 'error')
        except Exception as e:
            db.session.rollback()
            flash(f'Непредвиденная ошибка при импорте: {e}', 'error')
            
    else:
        flash('Неверный формат файла. Требуется .json.', 'error')
        
    return redirect(url_for('create_test'))

@app.route('/test/start/<int:test_id>')
def test_start(test_id):
    current_user = get_current_user()
    if not current_user:
        flash('Для прохождения теста необходимо войти.', 'error')
        return redirect(url_for('login'))
    
    test = Test.query.get_or_404(test_id)
    
    question_ids = [q.id for q in test.questions]
    
    if not question_ids:
        flash('В этом тесте пока нет вопросов.', 'error')
        return redirect(url_for('index'))

    session['test_progress'] = {
        'test_id': test_id,
        'question_ids': question_ids,
        'current_q_index': 0,
        'score': 0,
        'total_questions': len(question_ids)
    }
    return redirect(url_for('test_question'))

@app.route('/test/question')
def test_question():
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))
    
    if 'test_progress' not in session:
        flash('Тест не был начат.', 'info')
        return redirect(url_for('index'))

    progress = session['test_progress']
    q_index = progress['current_q_index']
    
    if q_index >= progress['total_questions']:
        flash('Тест завершен.', 'info')
        return redirect(url_for('profile'))
        
    current_q_id = progress['question_ids'][q_index]
    
    question = Question.query.get_or_404(current_q_id)
    
    return render_template('test_page.html', 
                            question=question, 
                            current_q_num=q_index + 1, 
                            total_questions=progress['total_questions'])

@app.route('/test/answer', methods=['POST'])
def test_answer():
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))
    
    if 'test_progress' not in session:
        return redirect(url_for('index'))
    
    selected_option_id = request.form.get('option')
    if not selected_option_id:
        flash('Пожалуйста, выберите вариант ответа.', 'error')
        return redirect(url_for('test_question'))
    
    selected_option = Option.query.get(selected_option_id)
    if selected_option and selected_option.is_correct:
        session['test_progress']['score'] += 1
    
    session['test_progress']['current_q_index'] += 1
    
    session.modified = True
    
    progress = session['test_progress']
    
    if progress['current_q_index'] >= progress['total_questions']:
        new_result = Result(
            user_id=current_user.id,
            test_id=progress['test_id'],
            score=progress['score']
        )
        db.session.add(new_result)
        db.session.commit()
        
        final_score = progress['score']
        total = progress['total_questions']
        session.pop('test_progress', None)
        
        flash(f'Тест завершен! Ваш результат: {final_score} из {total}!', 'success')
        return redirect(url_for('profile'))
        
    
    return redirect(url_for('test_question'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

        if not User.query.filter_by(username='admin').first():
            admin_user = User(
                username='admin',
                password_hash=generate_password_hash('adm1n', method='pbkdf2:sha256'),
                is_admin=True
            )
            db.session.add(admin_user)
            db.session.commit()


    app.run(debug=True)
