FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install .
RUN useradd --uid 10001 --create-home appuser && chown -R appuser:appuser /app
USER appuser
CMD ["python","-c","from multimodal_studio.planner import plan,to_json; print(to_json(plan('cinematic slow motion subtitles')))"]
