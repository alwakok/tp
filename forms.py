from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SelectField, BooleanField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError
from models import User


class LoginForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    remember_me = BooleanField('Запомнить меня')


class RegisterForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Пароль', validators=[DataRequired(), Length(min=8)])
    password2 = PasswordField('Повторите пароль', validators=[DataRequired(), EqualTo('password')])

    def validate_username(self, username):
        if User.query.filter_by(username=username.data).first():
            raise ValidationError('Имя пользователя уже занято')

    def validate_email(self, email):
        if User.query.filter_by(email=email.data).first():
            raise ValidationError('Email уже зарегистрирован')


class TicketForm(FlaskForm):
    subject = StringField('Тема', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Описание', validators=[DataRequired()])
    priority = SelectField('Приоритет', choices=[
        ('low', 'Низкий'), ('medium', 'Средний'),
        ('high', 'Высокий'), ('critical', 'Критический')
    ], default='medium')
    category_id = SelectField('Категория', coerce=int, validators=[DataRequired()])


class CommentForm(FlaskForm):
    content = TextAreaField('Комментарий', validators=[DataRequired()])


class UserForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Пароль', validators=[DataRequired(), Length(min=8)])
    role = SelectField('Роль', choices=[
        ('requester', 'Заявитель'), ('operator', 'Оператор'),
        ('executor', 'Исполнитель'), ('manager', 'Руководитель'),
        ('admin', 'Администратор')
    ], default='requester')


class CategoryForm(FlaskForm):
    name = StringField('Название категории', validators=[DataRequired(), Length(max=80)])