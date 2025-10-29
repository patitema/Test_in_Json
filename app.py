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
    """Получает объект User из БД, если user_id есть в сессии. Иначе возвращает None."""
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
    
    # КРИТИЧЕСКАЯ ПРОВЕРКА: Если пользователя нет в сессии, перенаправляем на вход
    if not current_user:
        flash('Пожалуйста, войдите, чтобы просмотреть ваш профиль.', 'error')
        return redirect(url_for('login'))
        
    # ИЗМЕНЕНИЕ ЗДЕСЬ: Загружаем все результаты пользователя
    # SQLAlchemy автоматически подтянет связанный объект Test благодаря db.relationship
    user_results = Result.query.filter_by(user_id=current_user.id).order_by(Result.date_completed.desc()).all()
    
    # Теперь user_results содержит реальные данные из БД
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
    # Находим сам тест
    test = Test.query.get_or_404(test_id)
    
    # Загружаем все результаты для этого теста.
    # Явно указываем joinload('user') для эффективной загрузки данных пользователя
    results = Result.query.filter_by(test_id=test_id).options(db.joinedload(Result.user)).order_by(Result.date_completed.desc()).all()
    
    # Получаем общее количество вопросов (для расчета процентов)
    total_questions = len(test.questions)
    
    return render_template('test_results.html', 
                           test=test, 
                           results=results, 
                           total_questions=total_questions)

# Замените ВЕСЬ код функции create_test на этот
@app.route('/admin/create_test', methods=['GET', 'POST'])
@admin_required
def create_test():
    if request.method == 'POST':
        questions_to_process = {} 
        
        # --- ОТЛАДКА 1: Проверка входных данных ---
        print(f"\n--- Начало обработки POST-запроса ---")
        print(f"Форма содержит ключей: {len(request.form)}")
        
        # 1. Надежный сбор данных из request.form (код остается прежним)
        for key, value in request.form.items():
            
            # Пропускаем общие поля теста
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
                    # 🛑 ТОЧКА ПЕРЕНАПРАВЛЕНИЯ 1
                    print(f"ОШИБКА 1: Неверный формат времени для вопроса {q_id}. Значение: '{value}'")
                    flash(f'Ошибка: Неверный формат времени для вопроса {q_id}.', 'error')
                    return redirect(url_for('create_test'))

            elif key.endswith('_correct'):
                questions_to_process[q_id]['correct_option_index'] = value
            
            elif '_option_text_' in key:
                o_index = parts[-1] 
                questions_to_process[q_id]['options'][o_index] = value

        # --- ОТЛАДКА 2: Проверка собранных вопросов ---
        print(f"Сырые данные вопросов: {questions_to_process}")

        # 2. Создание Теста и сохранение в БД
        title = request.form.get('title')
        description = request.form.get('description')
        test_difficulty = request.form.get('test_difficulty', 'Средний')
        
        valid_questions = {k: v for k, v in questions_to_process.items() if v.get('text', '').strip()}
        
        # --- ОТЛАДКА 3: Проверка количества действительных вопросов ---
        print(f"Действительных вопросов (с текстом): {len(valid_questions)}")
        
        if len(valid_questions) < 2:
             # 🛑 ТОЧКА ПЕРЕНАПРАВЛЕНИЯ 2
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
                    # Пропускаем вопрос, но продолжаем цикл
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
                
                # ... (Сохранение Вариантов - код остается прежним) ...
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

            # --- ОТЛАДКА 4: Финальная проверка количества вопросов ---
            print(f"Финальное количество сохраненных вопросов: {questions_count}")
            
            if questions_count < 2:
                # 🛑 ТОЧКА ПЕРЕНАПРАВЛЕНИЯ 3
                print("ОШИБКА 3: В базе сохранено меньше 2 вопросов. Откат транзакции.")
                db.session.rollback()
                flash('Тест отменен: в нем должно быть минимум 2 действительных вопроса.', 'error')
                return redirect(url_for('create_test'))

            db.session.commit()
            print(f"УСПЕХ: Тест '{title}' создан. Вопросов: {questions_count}")
            flash(f'Тест "{title}" успешно создан! Добавлено вопросов: {questions_count}', 'success')
            return redirect(url_for('index'))

        except Exception as e:
            # 🛑 ТОЧКА ПЕРЕНАПРАВЛЕНИЯ 4
            db.session.rollback()
            print(f"\n--- КРИТИЧЕСКАЯ ОШИБКА БД: {e} ---") 
            flash(f'Критическая ошибка при сохранении теста в БД. Подробности в логах сервера.', 'error')
            return redirect(url_for('create_test'))

    return render_template('create_test.html')

@app.route('/admin/delete_test/<int:test_id>', methods=['POST'])
@admin_required # <--- Только для администраторов
def delete_test(test_id):
    test_to_delete = Test.query.get_or_404(test_id)
    test_title = test_to_delete.title # Сохраняем название для сообщения

    try:
        # 1. Удаление всех связанных записей (CASCADE DELETE):
        # В идеале, ваши модели SQLAlchemy должны иметь CASCADE DELETE
        # настроенный для Question, Option и Result, но делаем явно для надежности:
        
        # Удаляем результаты, связанные с тестом
        Result.query.filter_by(test_id=test_id).delete()
        
        # Удаляем варианты, связанные с вопросами этого теста
        questions = Question.query.filter_by(test_id=test_id).all()
        question_ids = [q.id for q in questions]
        
        if question_ids:
            Option.query.filter(Option.question_id.in_(question_ids)).delete(synchronize_session=False)

        # Удаляем вопросы
        Question.query.filter_by(test_id=test_id).delete(synchronize_session=False)

        # 2. Удаление самого теста
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
            # Чтение и декодирование JSON
            json_data = json.load(file.stream)

            # Проверка основных полей теста
            title = json_data.get('title')
            description = json_data.get('description')
            test_difficulty = json_data.get('difficulty', 'Средний')
            questions_data = json_data.get('questions')

            if not all([title, questions_data, isinstance(questions_data, list)]):
                flash('JSON имеет неверную структуру (отсутствует title или questions).', 'error')
                return redirect(url_for('create_test'))

            # Создание Теста
            new_test = Test(title=title, description=description, difficulty=test_difficulty)
            db.session.add(new_test)
            db.session.flush()

            # Сохранение Вопросов и Вариантов
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
    
    # Получаем ID всех вопросов и перемешиваем их (опционально)
    question_ids = [q.id for q in test.questions]
    # import random
    # random.shuffle(question_ids) 
    
    if not question_ids:
        flash('В этом тесте пока нет вопросов.', 'error')
        return redirect(url_for('index'))

    # Инициализируем сессию для этого теста
    session['test_progress'] = {
        'test_id': test_id,
        'question_ids': question_ids,
        'current_q_index': 0, # Начинаем с первого вопроса
        'score': 0,
        'total_questions': len(question_ids)
    }
    
    # Перенаправляем на роут, который отображает сам вопрос
    return redirect(url_for('test_question'))

# 2. ОТОБРАЖЕНИЕ ВОПРОСА
# 2. ОТОБРАЖЕНИЕ ВОПРОСА
@app.route('/test/question')
def test_question():
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))
    
    # Проверяем, идет ли тест
    if 'test_progress' not in session:
        flash('Тест не был начат.', 'info')
        return redirect(url_for('index'))

    progress = session['test_progress']
    q_index = progress['current_q_index']
    
    # Проверка на завершение теста (хотя это должно происходить в test_answer)
    if q_index >= progress['total_questions']:
        # В случае, если пользователь как-то "перешел" лимит
        flash('Тест завершен.', 'info')
        return redirect(url_for('profile')) 
        
    # Получаем ID текущего вопроса
    current_q_id = progress['question_ids'][q_index]
    
    # 🚀 УПРОЩЕНИЕ: Загружаем вопрос. 
    # Благодаря lazy='joined' в модели, варианты загрузятся автоматически.
    question = Question.query.get_or_404(current_q_id)
    
    return render_template('test_page.html', 
                            question=question, 
                            current_q_num=q_index + 1, 
                            total_questions=progress['total_questions'])

# 3. ОБРАБОТКА ОТВЕТА (Кнопка "Следующий вопрос")
@app.route('/test/answer', methods=['POST'])
def test_answer():
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))
    
    if 'test_progress' not in session:
        return redirect(url_for('index'))
    
    # Получаем ID выбранного варианта
    selected_option_id = request.form.get('option')
    if not selected_option_id:
        flash('Пожалуйста, выберите вариант ответа.', 'error')
        return redirect(url_for('test_question'))
    
    # Проверяем, правильный ли ответ
    selected_option = Option.query.get(selected_option_id)
    if selected_option and selected_option.is_correct:
        session['test_progress']['score'] += 1
    
    # Переходим к следующему вопросу
    session['test_progress']['current_q_index'] += 1
    
    # Важно: Сохраняем изменения в сессии (Flask делает это обычно, но для надежности)
    session.modified = True 
    
    progress = session['test_progress']
    
    # 4. ЗАВЕРШЕНИЕ ТЕСТА
    if progress['current_q_index'] >= progress['total_questions']:
        # Тест окончен! Сохраняем результат в БД
        
        new_result = Result(
            user_id=current_user.id,
            test_id=progress['test_id'],
            score=progress['score']
        )
        db.session.add(new_result)
        db.session.commit()
        
        # Очищаем сессию
        final_score = progress['score']
        total = progress['total_questions']
        session.pop('test_progress', None) 
        
        flash(f'Тест завершен! Ваш результат: {final_score} из {total}!', 'success')
        return redirect(url_for('profile'))
    
    # Если тест не окончен, перенаправляем на следующий вопрос
    return redirect(url_for('test_question'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

        if not User.query.filter_by(username='admin').first():

            admin_user = User(
                username='admin',
                password_hash=generate_password_hash('sex', method='pbkdf2:sha256'),
                is_admin=True
            )
            db.session.add(admin_user)
            db.session.commit()
            print("Добавлен тестовый администратор (Логин: admin, Пароль: sex)")


    app.run(debug=True)
