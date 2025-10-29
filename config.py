import os

basedir = os.path.abspath(os.path.dirname(__file__))

SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'data', 'Tests.db')

SQLALCHEMY_TRACK_MODIFICATIONS = False 

SECRET_KEY = 's65d4s-465d4sd98s7-4d6s54d-s654dsd24'