FROM python:3.13-slim AS build
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY platesmith ./platesmith
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.13-slim
COPY --from=build /install /usr/local
RUN useradd --system --no-create-home platesmith
USER platesmith
EXPOSE 8137
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8137/', timeout=2)"]
CMD ["platesmith", "--host", "0.0.0.0", "--port", "8137"]
