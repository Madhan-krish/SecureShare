# SecureShare: Secure Group Data Sharing in Cloud

SecureShare is a robust, cloud-based web application built with Flask that enables secure file sharing, communication, and management within groups. It is designed to ensure data confidentiality and integrity by leveraging advanced encryption and compression techniques before storing files in the cloud (AWS S3). The system employs a Role-Based Access Control (RBAC) model, distinguishing between Data Owners, Data Members, and Third-Party Auditors (TPA) for comprehensive security and auditing.

## 🚀 Key Features

*   **Role-Based Access Control (RBAC):**
    *   **Data Owner:** Can create groups, add members natively via email, upload/encrypt files, and monitor group activity/logs.
    *   **Data Member:** Can join groups (with owner approval), view/download decrypted files, and communicate within the group.
    *   **Third-Party Auditor (TPA):** Monitors the integrity of files, verifies file hashes, and tracks user actions without accessing the actual plaintext data.
*   **Military-Grade Security:** Files are compressed using `lzma` (preset 9) and subsequently encrypted using strong symmetric encryption (`Cryptography Fernet`) before making their way natively to AWS S3.
*   **Real-Time Chat:** Integrated WebSockets (via `Flask-SocketIO`) enables seamless, real-time messaging and file sharing directly within the chat interface.
*   **OTP-Based Authentication:** Employs standard SMTP via `Flask-Mail` to provide OTP validation during user registration and password resets, preventing unauthorized account creation.
*   **Secure Cloud Storage:** Decoupled storage architecture utilizing MongoDB Atlas for fast metadata retrieval and AWS S3 for scalable encrypted file blob storage.
*   **Automated Storage Management:** Features a 30-day auto-cleanup script for files moved to the bin to optimize storage resources safely.
*   **Live Dashboard & Analytics:** Intuitive UI providing insights into file counts, storage savings percentages (due to compression), and recent team activities.

## 🛠️ Technology Stack

*   **Backend:** Python, Flask, Flask-SocketIO
*   **Database:** MongoDB Atlas (PyMongo)
*   **Cloud Storage:** AWS S3 (Boto3)
*   **Security & Encryption:** `cryptography` (Fernet), `hashlib` (SHA-256), `lzma` (Compression), `werkzeug.security` (Password Hashing)
*   **Frontend:** HTML5, CSS3, JavaScript (Jinja2 Templates)
*   **Communication:** Flask-Mail (SMTP for OTPs)

## ⚙️ Prerequisites

Before you begin, ensure you have met the following requirements:
*   Python 3.8+ installed
*   A MongoDB Atlas cluster with connection URI
*   An AWS account with S3 Bucket and IAM User credentials (Access Key ID & Secret Access Key)
*   An SMTP email server for sending OTPs (e.g., Gmail App Passwords)

## 📥 Installation & Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Madhan-krish/SecureShare.git
    cd SecureShare
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    # On Windows:
    venv\Scripts\activate
    # On macOS/Linux:
    source venv/bin/activate
    ```

3.  **Install the dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: Ensure `Flask`, `Flask-SocketIO`, `pymongo`, `cryptography`, `boto3`, `Flask-Mail`, and `python-dotenv` are specified in your requirements file).*

4.  **Configure Environment Variables:**
    Create a `.env` file in the root directory and add your credentials:
    ```env
    AWS_ACCESS_KEY=your_aws_access_key
    AWS_SECRET_KEY=your_aws_secret_key
    AWS_REGION=us-east-1
    S3_BUCKET_NAME=your_s3_bucket_name
    ```

5.  **Review the Application Configuration:**
    *   Update `MONGO_URI` inside `app.py` or preferably move it to your `.env` file.
    *   Update standard `app.config['MAIL_USERNAME']` and `app.config['MAIL_PASSWORD']` (Use App Passwords for Gmail) inside `app.py`.

6.  **Run the Application:**
    ```bash
    python app.py
    ```

7.  **Access the Application:**
    Open your web browser and navigate to `http://127.0.0.1:5000/`.

## 📁 Project Structure

*   `app.py`: The main Flask application containing routing, websocket logic, and DB connection setup.
*   `templates/`: Contains all Jinja2 HTML templates for rendering pages (Dashboard, Login, Register, TPA Portal, etc.).
*   `uploads/`: Temporary local directory used for streaming files before encryption and upload to S3.
*   `requirements.txt`: List of Python dependencies. *(Ensure this file exists or generate using `pip freeze > requirements.txt`)*


