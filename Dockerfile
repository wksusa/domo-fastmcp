# Use the official Python image as a base
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port the app runs on
EXPOSE 8000

# Define environment variables (replace with actual values or use secrets management)
ENV DOMO_DEVELOPER_TOKEN=""
ENV DOMO_HOST=""

# Run the application
CMD ["python", "-m", "domo_mcp"]