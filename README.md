# 📚 Student Support AI

<p align="center">
  <strong>An AI-powered academic learning and study assistant for VTU Computer Science students</strong>
</p>

<p align="center">
  Access subject-wise study materials, prepare important questions, manage personal notes, explore learning resources, and get AI-powered academic assistance in one place.
</p>

<p align="center">
  <a href="https://student-support-vtu.vercel.app/login">
    <img src="https://img.shields.io/badge/🚀_Live_Demo-Visit_App-success?style=for-the-badge" alt="Live Demo">
  </a>
  <a href="https://github.com/Vinay9686803463/student-support-ai">
    <img src="https://img.shields.io/badge/💻_Repository-GitHub-black?style=for-the-badge&logo=github" alt="GitHub Repository">
  </a>
</p>


---

## 🛠️ Tech Stack

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white" alt="Flask">
  <img src="https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white" alt="HTML5">
  <img src="https://img.shields.io/badge/CSS3-1572B6?style=for-the-badge&logo=css3&logoColor=white" alt="CSS3">
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black" alt="JavaScript">
  <img src="https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/AI_Powered-6C63FF?style=for-the-badge" alt="AI Powered">
</p>

---

## ✨ Features

- 🤖 **AI Study Assistant** — Ask academic questions and receive explanations to support your learning.
- 📚 **Semester-Wise Subjects** — Browse VTU Computer Science subjects by semester.
- 📖 **Study Materials** — Access subject-specific study materials organized by modules.
- ❓ **Important Questions** — Find and filter important questions for exam preparation.
- 📝 **Personal Notes** — Create and manage your own study notes.
- 🔗 **Learning Resources** — Access curated VTU and NPTEL learning resources.
- 🔐 **Authentication** — User registration, login, and password recovery features.
- 📊 **Dashboard** — Access study features and relevant dashboard statistics.
- 👤 **Profile and Preferences** — Manage supported account settings.
- 🧠 **Knowledge-Based Answers** — Use available knowledge-base and retrieval features to improve academic responses.
- 🔄 **AI Provider Fallback** — Use configured fallback options where supported.
- 🌙 **Modern User Interface** — A responsive study interface with a dark theme and blue-purple accents.

---

## 📁 Project Structure

```text
student-support-ai/
│
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
│
├── templates/
│   ├── chat.html
│   └── ...
│
├── static/
│   ├── css/
│   ├── js/
│   └── images/
│
├── utils/
│   ├── ai.py
│   ├── database.py
│   ├── rag.py
│   ├── rag_ai.py
│   └── ...
│
├── knowledge_base/
│   └── ...
│
├── tests/
│   └── ...
│
└── .env.example
```
---

## 💻 Run Locally

### 1. Clone the repository

```bash
git clone https://github.com/Vinay9686803463/student-support-ai.git
cd student-support-ai
```

### 2. Create a virtual environment

**Windows PowerShell:**

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Linux/macOS:**

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root, in the same directory as `app.py`.

Configure the environment variables required by your selected AI provider and database. Check the application's configuration and `.env.example` (if available) for the exact variable names.

**Example for Gemini, if enabled in your configuration:**

```dotenv
AI_PROVIDER=gemini
GOOGLE_GENERATIVE_AI_API_KEY=your_google_ai_api_key
```

Replace the placeholder with your own API key. Add any required database URL or application secret using the variable names expected by the project.

**Security:** Never commit `.env` files, API keys, passwords, or production database credentials to GitHub.

### 5. Start the application

```bash
python app.py
```

### 6. Open the application

Open this address in your browser:

```text
http://127.0.0.1:5000/
```

If the root URL does not redirect automatically, open the login route configured by the application.

---

## 🤖 AI Assistant

Student Support AI is designed to help students understand technical concepts, revise syllabus topics, and prepare for examinations.

Depending on the configured provider and available resources, the application can support:

- Academic explanations and concept clarification.
- Subject-related question answering.
- Retrieval of relevant study materials from the knowledge base.
- AI provider fallback and alternative response paths.
- Streaming responses where enabled.

AI availability and response quality depend on provider configuration, network access, and the resources available to the application.

---

## 🗄️ Database and Study Materials

The application supports database utilities for managing academic content and user-related information.

- **SQLite:** Useful for local development and testing.
- **PostgreSQL:** Supported where the deployment and database configuration are set up accordingly.
- **Knowledge Base:** Stores or organizes subject-related material used by supported retrieval features.
- **Study Resources:** Organized to help students find material relevant to their semester and subjects.

For production, use a properly configured persistent database and follow the project's existing database initialization and migration procedures. Back up important data before performing schema changes.

---

## 🚀 Deployment

Student Support AI can be deployed to a compatible hosting platform, depending on the repository's deployment configuration.

### Deployment checklist

1. Push the reviewed changes to the GitHub repository.
2. Connect the repository to the chosen hosting platform.
3. Configure the required environment variables in the hosting dashboard.
4. Configure the database and persistent storage where needed.
5. Verify AI provider configuration and network access.
6. Deploy and inspect application logs.
7. Test login, study materials, chat responses, and other important features.

### ⚠️ Production considerations

- Keep all API keys and application secrets server-side.
- Configure a persistent database for production data.
- Verify that uploaded study materials and generated indexes are stored appropriately.
- Test database migrations and recovery procedures before applying them to production.

---

## 🌐 Project Links

| Resource | Link |
|---|---|
| 🚀 **Live Demo** | [Student-Support-AI](https://student-support-vtu.vercel.app/login) |
| 💻 **GitHub Repository** | [Student Support AI Repository](https://github.com/Vinay9686803463/student-support-ai) |

---

## 🔮 Future Improvements

- 📈 Enhanced study progress analytics.
- 📄 More downloadable study resources.
- 🎯 Personalized revision plans and study recommendations.
- 🧪 Improved automated testing and response evaluation.
- ⚡ Faster AI response generation and retrieval.
- 🌐 Additional learning resources and subject coverage.
- 📱 Further improvements to the mobile experience.

---

## 👨‍💻 Author

**Vinay Sollapure**

Built to help VTU Computer Science students organize study materials, prepare for examinations, and explore AI-assisted learning.

---

<p align="center">
  ⭐ If you find this project useful, consider giving it a star on GitHub!
</p>
