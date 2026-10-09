from app import app
from utils.database import db, Subject


with app.app_context():

    print("Removing old subjects table...")

    Subject.__table__.drop(
        bind=db.engine,
        checkfirst=True
    )

    print("Creating new subjects table...")

    Subject.__table__.create(
        bind=db.engine,
        checkfirst=True
    )

    print("Subjects table recreated successfully.")