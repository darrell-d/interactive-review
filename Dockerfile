FROM python:3.12-slim

WORKDIR /app

COPY processor/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY processor/ /app/processor/

ENV PYTHONPATH="/app"

# Run as uid/gid 1000, not root. The platform runs the container as 1000
# whatever the image says and hands that user its data disk; the same user
# here keeps a local run like a real one.
RUN groupadd -g 1000 appuser && useradd -u 1000 -g 1000 -m -s /bin/bash appuser
USER 1000:1000

# Interactive sessions run only as ECS/Fargate tasks: a web app that waits
# for a person can't run on Lambda.
ENTRYPOINT ["python3", "-m", "processor.main"]
