import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))

SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'data', 'Tests.db')

SQLALCHEMY_TRACK_MODIFICATIONS = False 

load_dotenv()

SECRET_KEY = os.getenv('SECRET_KEY', 'dev')
