# STRATA数智教学系统

新版平台后端底座，目标是私有化部署、局域网离线运行。

## 技术基线

- Python 3.12
- Django 5.2 LTS
- Django REST Framework
- Django Channels + Redis
- Celery + django-celery-beat
- PostgreSQL production target
- SQLite local bootstrap fallback

## 本地启动

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

健康检查：

```text
http://127.0.0.1:8000/api/health/
```

## 离线依赖

联网机器执行：

```powershell
.\scripts\make_wheelhouse.ps1
```

把整个项目目录带到离线局域网服务器后执行：

```powershell
.\scripts\install_offline.ps1
```

## 数据库切换

当前 `.env` 默认为 SQLite，便于没有 PostgreSQL 的开发机启动。

生产/局域网服务器安装 PostgreSQL 后，将 `.env` 改为：

```env
DATABASE_ENGINE=postgresql
DATABASE_NAME=xlzxedu
DATABASE_HOST=127.0.0.1
DATABASE_PORT=5432
DATABASE_USER=xlzxedu
DATABASE_PASSWORD=your-private-password
```

然后执行：

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```
