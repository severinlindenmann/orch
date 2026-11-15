FROM python:3.12-slim
# The host runs this image as user id 61000 and a read-only root: write only to $DATA_DIR.
WORKDIR /app
COPY . /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Listen on $HOST:$PORT (the host sets both), serve under $BASE_PATH.
CMD ["python3", "main.py"]
