# LogiEdge inference container (Task D2). Build from the repository root:
#   docker build -f inference/Dockerfile -t logibridge-inference:1.0 .
FROM python:3.11-slim
WORKDIR /app

# 1. Dependencies: the slowest layer, cached across model updates
COPY inference/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Code and normalisation stats: change rarely
COPY data_pipeline/preprocessing.py .
COPY inference/tflite_runner.py inference/inference_service.py ./
COPY data_pipeline/training_stats.npy .

# 3. Runtime configuration (metadata only)
ENV MODEL_PATH=/app/model.tflite \
    TRUCK_ID=TRUCK_001 \
    MQTT_HOST=localhost \
    MQTT_PORT=1883
CMD ["python", "-u", "inference_service.py"]

# 4. The model changes every ~6 weeks, so it comes last:
#    an OTA model update rebuilds and ships only this layer.
COPY inference/model.tflite .
