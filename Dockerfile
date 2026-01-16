# Start from a base Python image
FROM python:3.12-slim

# For debugging purposes, install curl
RUN apt update && apt install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*
    
# Set the working directory
WORKDIR /app

# Copy the requirements file first to leverage Docker cache
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
# This includes the 'semantic_scholar' package and 'run.py'
COPY . /app
# Alternatively, be more specific:
# COPY semantic_scholar /app/semantic_scholar
# COPY run.py /app/run.py

# Expose the port that the MCP server will run on
EXPOSE 8000

# Set the environment variable for the API key (placeholder)
# Glama or the user should provide the actual key at runtime
ENV SEMANTIC_SCHOLAR_API_KEY=""

# Command to run the server using the refactored entry point
CMD ["python", "run.py"]