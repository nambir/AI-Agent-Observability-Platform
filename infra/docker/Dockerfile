FROM python:3.11-slim
WORKDIR /app
COPY apps /app/apps
RUN mkdir -p /app/data
ENV OBSERVABILITY_HOST=0.0.0.0
ENV OBSERVABILITY_PORT=8300
EXPOSE 8300
CMD ["python", "/app/apps/api/main.py"]
