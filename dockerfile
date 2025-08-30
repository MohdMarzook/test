FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Combine all apt operations in a single layer and clean up in the same step
RUN apt-get update && \
    apt-get install -y --no-install-recommends wget && \
    # Download and install both .deb files in one layer
        wget -q http://mirrors.kernel.org/ubuntu/pool/main/libj/libjpeg-turbo/libjpeg-turbo8_2.1.2-0ubuntu1_amd64.deb && \
        wget -q https://github.com/pdf2htmlEX/pdf2htmlEX/releases/download/v0.18.8.rc1/pdf2htmlEX-0.18.8.rc1-master-20200630-Ubuntu-focal-x86_64.deb && \
        # Install .deb files
    apt-get install -y --no-install-recommends ./libjpeg-turbo8_2.1.2-0ubuntu1_amd64.deb && \
    apt-get install -y --no-install-recommends ./pdf2htmlEX-0.18.8.rc1-master-20200630-Ubuntu-focal-x86_64.deb && \
    # Clean up in the same layer
    rm -f *.deb && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


COPY ./app .

RUN pip install -r requirements.txt

CMD ["celery", "-A", "task", "worker", "--concurrency=4", "--loglevel=info", "--pool=processes"]
# CMD ["celery", "-A", "task", "worker", "--loglevel=info", "-c", "4"]
# CMD ["python", "task.py"]