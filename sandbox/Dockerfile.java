# Sandbox image for Java projects (Maven, Gradle wrapper, or plain javac). Build:
#   docker build -f sandbox/Dockerfile.java -t fixengine-sandbox-java:1 sandbox
FROM maven:3.9-eclipse-temurin-21
RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox \
 && mkdir -p /work && chown 10001:10001 /work
COPY smoke.py /opt/smoke.py
ENV HOME=/tmp MAVEN_OPTS="-Duser.home=/tmp" JAVA_TOOL_OPTIONS="-Duser.home=/tmp" CI=1
USER 10001
WORKDIR /work
