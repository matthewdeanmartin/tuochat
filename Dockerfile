FROM public.ecr.aws/lambda/python:3.14

# Install uv for faster dependency management
RUN pip install --no-cache-dir uv

# Set the working directory to the Lambda task root
WORKDIR ${LAMBDA_TASK_ROOT}

# Copy the project files
COPY . .

# Install dependencies and the project with the [all] extra
RUN uv pip install --system --no-cache-dir ".[all]"

# Default command for the CLI tool
# This can be overridden when running the container
ENTRYPOINT ["python3", "-m", "tuochat"]
CMD ["--help"]
