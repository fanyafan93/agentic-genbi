import os


os.environ.setdefault(
    "DATABASE_URL",
    "mysql+pymysql://readonly_user:readonly-password@localhost:3306/analytics",
)
