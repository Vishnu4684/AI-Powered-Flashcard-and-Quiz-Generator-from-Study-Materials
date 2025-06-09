import streamlit as st
import sqlite3
import os
import hashlib
import uuid
import datetime
import PyPDF2
import io
import json
import pandas as pd
import time
import plotly.express as px
import random
import google.generativeai as genai
from typing import List, Dict, Tuple, Any, Optional
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from dotenv import load_dotenv
load_dotenv()



DATABASE_FILE = "flashcard_app.db"
PDF_STORAGE_PATH = "uploaded_pdfs"
SESSION_TIMEOUT = 3600  


if not os.path.exists(PDF_STORAGE_PATH):
    os.makedirs(PDF_STORAGE_PATH)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('models/gemini-1.5-flash')


def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
   
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        filepath TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')
    
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS flashcards (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        front TEXT NOT NULL,
        back TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (document_id) REFERENCES documents (id)
    )
    ''')
    
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS quizzes (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (document_id) REFERENCES documents (id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')
    
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS questions (
        id TEXT PRIMARY KEY,
        quiz_id TEXT NOT NULL,
        question_text TEXT NOT NULL,
        correct_answer TEXT NOT NULL,
        option1 TEXT NOT NULL,
        option2 TEXT NOT NULL,
        option3 TEXT NOT NULL,
        FOREIGN KEY (quiz_id) REFERENCES quizzes (id)
    )
    ''')
    
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS quiz_attempts (
        id TEXT PRIMARY KEY,
        quiz_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        score INTEGER NOT NULL,
        total_questions INTEGER NOT NULL,
        completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (quiz_id) REFERENCES quizzes (id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')
    
    conn.commit()
    conn.close()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def generate_id() -> str:
    return str(uuid.uuid4())


def register_user(username: str, password: str, email: str) -> bool:
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        user_id = generate_id()
        password_hash = hash_password(password)
        
        cursor.execute(
            "INSERT INTO users (id, username, password_hash, email) VALUES (?, ?, ?, ?)",
            (user_id, username, password_hash, email)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def authenticate_user(username: str, password: str) -> Optional[str]:
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id, password_hash FROM users WHERE username = ?", 
        (username,)
    )
    result = cursor.fetchone()
    conn.close()
    
    if result and result[1] == hash_password(password):
        return result[0]  
    return None

def get_username_by_id(user_id: str) -> str:
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else ""


def save_uploaded_pdf(uploaded_file, user_id: str) -> Tuple[bool, str, str]:
    try:
        
        file_id = generate_id()
        filename = f"{file_id}_{uploaded_file.name}"
        filepath = os.path.join(PDF_STORAGE_PATH, filename)
        
        
        with open(filepath, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        
        text_content = ""
        with open(filepath, "rb") as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text_content += page.extract_text()
        
        
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        document_id = generate_id()
        
        cursor.execute(
            "INSERT INTO documents (id, user_id, title, filepath, content) VALUES (?, ?, ?, ?, ?)",
            (document_id, user_id, uploaded_file.name, filepath, text_content)
        )
        conn.commit()
        conn.close()
        
        return True, document_id, text_content
    except Exception as e:
        st.error(f"Error processing PDF: {str(e)}")
        return False, "", ""

def get_user_documents(user_id: str) -> List[Dict]:
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id, title, created_at FROM documents WHERE user_id = ? ORDER BY created_at DESC", 
        (user_id,)
    )
    documents = cursor.fetchall()
    conn.close()
    
    return [{"id": doc[0], "title": doc[1], "created_at": doc[2]} for doc in documents]

def get_document_content(document_id: str) -> str:
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT content FROM documents WHERE id = ?", (document_id,))
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else ""

def get_document_title(document_id: str) -> str:
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT title FROM documents WHERE id = ?", (document_id,))
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else ""

# Flashcard functions
def generate_flashcards(document_id: str, text_content: str) -> List[Dict]:
    try:
        
        prompt = f"""
        Create 10 flashcards from the following text. Each flashcard should be comprehensive and include at least 33% of the original content's key points.

        For each flashcard:
        1. The 'front' should be a key concept, term, or question
        2. The 'back' must be detailed and thorough, covering at least 33% of the relevant information from the source text
        3. Include examples, context, and explanations where appropriate
        4. Make sure the explanations are substantive and not oversimplified

        Format the result as a JSON array of objects, each with 'front' and 'back' properties.
        
        Text:
        {text_content[:7000]}  # Limiting to avoid token limits
        
        Response format:
        [
            {{"front": "Concept/Question", "back": "Detailed explanation that covers at least 33% of the relevant information from the source text"}},
            ...
        ]
        """
        
        
        response = gemini_model.generate_content(prompt)
        response_text = response.text
        
        
        if "```json" in response_text:
            json_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            json_text = response_text.split("```")[1].split("```")[0].strip()
        else:
            json_text = response_text
        
        flashcards = json.loads(json_text)
        
        
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        for card in flashcards:
            flashcard_id = generate_id()
            cursor.execute(
                "INSERT INTO flashcards (id, document_id, front, back) VALUES (?, ?, ?, ?)",
                (flashcard_id, document_id, card["front"], card["back"])
            )
        
        conn.commit()
        conn.close()
        
        return flashcards
    except Exception as e:
        st.error(f"Error generating flashcards: {str(e)}")
        return []

def get_document_flashcards(document_id: str) -> List[Dict]:
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id, front, back FROM flashcards WHERE document_id = ?",
        (document_id,)
    )
    flashcards = cursor.fetchall()
    conn.close()
    
    return [{"id": card[0], "front": card[1], "back": card[2]} for card in flashcards]


from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import io

def generate_flashcards_pdf(flashcards: list, document_title: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            leftMargin=50, rightMargin=50, topMargin=50, bottomMargin=30)
    styles = getSampleStyleSheet()

    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontSize=20, textColor=colors.darkblue, alignment=1, spaceAfter=15)
    flashcard_title_style = ParagraphStyle('FlashcardTitleStyle', parent=styles['Heading2'], fontSize=16, spaceAfter=10, textColor=colors.white, backColor=colors.darkred, alignment=1, leading=20)
    flashcard_front_style = ParagraphStyle('FrontStyle', parent=styles['Normal'], fontSize=14, leading=18, spaceAfter=5, textColor=colors.black, alignment=4)  # **Justified**
    flashcard_back_style = ParagraphStyle('BackStyle', parent=styles['Normal'], fontSize=12, leading=16, textColor=colors.darkblue, spaceAfter=10, alignment=4)  # **Justified**

    elements = []

    
    elements.append(Paragraph(f"{document_title}", title_style))
    elements.append(Spacer(1, 0.3 * inch))

    
    table_data = []
    for i, card in enumerate(flashcards):
        flashcard_title = Paragraph(f"<b>Flashcard {i+1}</b>", flashcard_title_style)
        front_side = Paragraph(f"<b>{card['front']}</b>", flashcard_front_style)
        back_side = Paragraph(f"{card['back']}", flashcard_back_style)

        
        table_data.append([flashcard_title])
        table_data.append([front_side])
        table_data.append([back_side])
        table_data.append([Spacer(1, 0.3 * inch)])  # Space between flashcards

    # **Apply Table Styling**
    table = Table(table_data, colWidths=[6.5 * inch])  # Adjust width to center text
    table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),  # Center everything
        ('LEFTPADDING', (0, 0), (-1, -1), 10),  # Ensure proper padding
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),  # Title background
    ]))

    elements.append(table)

    
    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    return pdf_bytes




def generate_quiz(document_id: str, user_id: str, document_content: str) -> Optional[str]:
    try:
        # First check if we have flashcards for this document
        flashcards = get_document_flashcards(document_id)
        
        # If no flashcards exist, generate some
        if not flashcards:
            flashcards = generate_flashcards(document_id, document_content)
            if not flashcards:
                return None
        
        # Create quiz in database
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        quiz_id = generate_id()
        doc_title = get_document_title(document_id)
        quiz_title = f"Quiz on {doc_title}"
        
        cursor.execute(
            "INSERT INTO quizzes (id, document_id, user_id, title) VALUES (?, ?, ?, ?)",
            (quiz_id, document_id, user_id, quiz_title)
        )
        
        # Prepare the prompt for Gemini to create MCQs from flashcards
        flashcard_text = "\n".join([f"Topic: {card['front']}\nExplanation: {card['back']}" for card in flashcards])
        
        prompt = f"""
        Create 10 multiple-choice questions based on these flashcard topics:
        
        {flashcard_text}
        
        Format the result as a JSON array of objects, each with 'question_text', 'correct_answer', 'option1', 'option2', and 'option3' properties.
        The 'correct_answer' should be the right answer, and options should be plausible but incorrect alternatives.
        
        Response format:
        [
            {{
                "question_text": "Question goes here?",
                "correct_answer": "Correct answer",
                "option1": "Wrong option 1",
                "option2": "Wrong option 2",
                "option3": "Wrong option 3"
            }},
            ...
        ]
        """
        
        # Generate questions using Gemini API
        response = gemini_model.generate_content(prompt)
        response_text = response.text
        
        # Extract JSON from the response
        if "```json" in response_text:
            json_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            json_text = response_text.split("```")[1].split("```")[0].strip()
        else:
            json_text = response_text
        
        questions = json.loads(json_text)
        
        # Store questions in the database
        for question in questions:
            question_id = generate_id()
            cursor.execute(
                """INSERT INTO questions 
                   (id, quiz_id, question_text, correct_answer, option1, option2, option3) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (question_id, quiz_id, question["question_text"], question["correct_answer"], 
                 question["option1"], question["option2"], question["option3"])
            )
        
        conn.commit()
        conn.close()
        
        return quiz_id
    except Exception as e:
        st.error(f"Error generating quiz: {str(e)}")
        return None

def get_quiz_questions(quiz_id: str) -> List[Dict]:
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id, question_text, correct_answer, option1, option2, option3 FROM questions WHERE quiz_id = ?",
        (quiz_id,)
    )
    questions = cursor.fetchall()
    conn.close()
    
    return [{
        "id": q[0],
        "question_text": q[1],
        "correct_answer": q[2],
        "options": [q[2], q[3], q[4], q[5]]  # Correct answer + wrong options
    } for q in questions]

def shuffle_options(questions: List[Dict]) -> List[Dict]:
    # Shuffle the options for each question and track the correct answer
    shuffled_questions = []
    
    for q in questions:
        options = q["options"].copy()
        correct = q["correct_answer"]
        random.shuffle(options)
        
        shuffled_questions.append({
            "id": q["id"],
            "question_text": q["question_text"],
            "options": options,
            "correct_answer": correct
        })
    
    return shuffled_questions

def save_quiz_result(quiz_id: str, user_id: str, score: int, total_questions: int) -> bool:
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        attempt_id = generate_id()
        cursor.execute(
            "INSERT INTO quiz_attempts (id, quiz_id, user_id, score, total_questions) VALUES (?, ?, ?, ?, ?)",
            (attempt_id, quiz_id, user_id, score, total_questions)
        )
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error saving quiz result: {str(e)}")
        return False

def get_user_quizzes(user_id: str) -> List[Dict]:
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT q.id, q.title, q.created_at, d.title AS document_title
        FROM quizzes q
        JOIN documents d ON q.document_id = d.id
        WHERE q.user_id = ?
        ORDER BY q.created_at DESC
        """, 
        (user_id,)
    )
    quizzes = cursor.fetchall()
    conn.close()
    
    return [{"id": q[0], "title": q[1], "created_at": q[2], "document_title": q[3]} for q in quizzes]

def get_user_progress(user_id: str) -> Dict:
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # Get quiz attempt statistics
    cursor.execute(
        """
        SELECT 
            COUNT(*) AS total_attempts,
            SUM(score) AS total_correct,
            SUM(total_questions) AS total_questions,
            AVG(CAST(score AS FLOAT) / total_questions) * 100 AS average_score
        FROM quiz_attempts
        WHERE user_id = ?
        """, 
        (user_id,)
    )
    stats = cursor.fetchone()
    
    # Get attempts over time
    cursor.execute(
        """
        SELECT 
            completed_at,
            CAST(score AS FLOAT) / total_questions * 100 AS percentage
        FROM quiz_attempts
        WHERE user_id = ?
        ORDER BY completed_at
        """, 
        (user_id,)
    )
    attempts = cursor.fetchall()
    
    conn.close()
    
    # Prepare progress data
    if stats[0] > 0:  # If there are any attempts
        progress_data = {
            "total_attempts": stats[0],
            "total_correct": stats[1],
            "total_questions": stats[2],
            "average_score": round(stats[3], 2) if stats[3] else 0,
            "attempts": [{"date": a[0], "score": round(a[1], 2)} for a in attempts]
        }
    else:
        progress_data = {
            "total_attempts": 0,
            "total_correct": 0,
            "total_questions": 0,
            "average_score": 0,
            "attempts": []
        }
    
    return progress_data

# Session management
def init_session_state():
    if 'user_id' not in st.session_state:
        st.session_state.user_id = None
    if 'username' not in st.session_state:
        st.session_state.username = None
    if 'login_time' not in st.session_state:
        st.session_state.login_time = None
    if 'active_page' not in st.session_state:
        st.session_state.active_page = "login"
    if 'active_document' not in st.session_state:
        st.session_state.active_document = None
    if 'active_quiz' not in st.session_state:
        st.session_state.active_quiz = None
    if 'quiz_questions' not in st.session_state:
        st.session_state.quiz_questions = None
    if 'current_question' not in st.session_state:
        st.session_state.current_question = 0
    if 'user_answers' not in st.session_state:
        st.session_state.user_answers = {}
    if 'quiz_completed' not in st.session_state:
        st.session_state.quiz_completed = False
    if 'quiz_score' not in st.session_state:
        st.session_state.quiz_score = 0

def check_session_validity():
    if st.session_state.login_time:
        elapsed_time = time.time() - st.session_state.login_time
        if elapsed_time > SESSION_TIMEOUT:
            logout_user()
            st.warning("Your session has expired. Please log in again.")
            return False
        return True
    return False

def login_user(user_id: str, username: str):
    st.session_state.user_id = user_id
    st.session_state.username = username
    st.session_state.login_time = time.time()
    st.session_state.active_page = "dashboard"

def logout_user():
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.login_time = None
    st.session_state.active_page = "login"
    st.session_state.active_document = None
    st.session_state.active_quiz = None
    st.session_state.quiz_questions = None
    st.session_state.current_question = 0
    st.session_state.user_answers = {}
    st.session_state.quiz_completed = False
    st.session_state.quiz_score = 0

# UI Components
def render_login_page():
    st.title("AI Flashcard & Quiz System")
    
    tab1, tab2 = st.tabs(["Login", "Register"])
    
    with tab1:
        st.subheader("Login")
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        
        if st.button("Login", key="login_button"):
            if username and password:
                user_id = authenticate_user(username, password)
                if user_id:
                    login_user(user_id, username)
                    st.success("Login successful!")
                    st.rerun()
                else:
                    st.error("Invalid username or password")
            else:
                st.warning("Please enter username and password")
    
    with tab2:
        st.subheader("Register")
        new_username = st.text_input("Username", key="reg_username")
        new_email = st.text_input("Email", key="reg_email")
        new_password = st.text_input("Password", type="password", key="reg_password")
        confirm_password = st.text_input("Confirm Password", type="password", key="reg_confirm")
        
        if st.button("Register", key="register_button"):
            if new_username and new_email and new_password:
                if new_password != confirm_password:
                    st.error("Passwords don't match")
                elif len(new_password) < 6:
                    st.error("Password should be at least 6 characters")
                else:
                    if register_user(new_username, new_password, new_email):
                        st.success("Registration successful! Please login.")
                    else:
                        st.error("Username or email already exists")
            else:
                st.warning("Please fill all fields")

def render_sidebar():
    st.sidebar.title(f"Hello, {st.session_state.username}!")
    
    # Navigation menu
    st.sidebar.header("Navigation")
    
    if st.sidebar.button("Dashboard"):
        st.session_state.active_page = "dashboard"
        st.session_state.active_document = None
        st.session_state.active_quiz = None
        st.rerun()
    
    if st.sidebar.button("Upload Document"):
        st.session_state.active_page = "upload"
        st.rerun()
    
    if st.sidebar.button("My Flashcards"):
        st.session_state.active_page = "flashcards"
        st.rerun()
    
    if st.sidebar.button("My Quizzes"):
        st.session_state.active_page = "quizzes"
        st.rerun()
    
    if st.sidebar.button("Progress Report"):
        st.session_state.active_page = "progress"
        st.rerun()
    
    # Logout button at the bottom
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout"):
        logout_user()
        st.rerun()

def render_dashboard():
    st.title("Dashboard")
    
    # Quick stats
    progress = get_user_progress(st.session_state.user_id)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Quizzes Taken", progress["total_attempts"])
    
    with col2:
        st.metric("Questions Answered", progress["total_questions"])
    
    with col3:
        st.metric("Average Score", f"{progress['average_score']}%")
    
    # Recent documents
    st.subheader("Your Recent Documents")
    documents = get_user_documents(st.session_state.user_id)
    
    if documents:
        for doc in documents[:5]:  # Show only the 5 most recent
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"📚 {doc['title']}")
            with col2:
                if st.button("View", key=f"view_{doc['id']}"):
                    st.session_state.active_page = "document"
                    st.session_state.active_document = doc['id']
                    st.rerun()
    else:
        st.info("You haven't uploaded any documents yet. Click on 'Upload Document' to get started!")
    
    # Quick actions
    st.subheader("Quick Actions")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("Upload New Document"):
            st.session_state.active_page = "upload"
            st.rerun()
    
    with col2:
        if st.button("Take a Quiz"):
            st.session_state.active_page = "quizzes"
            st.rerun()

def render_upload_page():
    st.title("Upload Document")
    
    st.write("Upload a PDF document to generate flashcards and quizzes.")
    
    uploaded_file = st.file_uploader("Choose a PDF file", type=["pdf"])
    
    if uploaded_file is not None:
        if st.button("Process Document"):
            with st.spinner("Processing document..."):
                success, document_id, content = save_uploaded_pdf(uploaded_file, st.session_state.user_id)
                
                if success:
                    st.success("Document uploaded successfully!")
                    
                    # Generate flashcards
                    with st.spinner("Generating flashcards..."):
                        flashcards = generate_flashcards(document_id, content)
                        if flashcards:
                            st.success(f"Generated {len(flashcards)} flashcards!")
                            
                            # Set active document
                            st.session_state.active_page = "document"
                            st.session_state.active_document = document_id
                            st.rerun()
                        else:
                            st.error("Failed to generate flashcards.")
                else:
                    st.error("Failed to upload document.")

def render_document_page():
    if not st.session_state.active_document:
        st.error("No document selected")
        return
    
    document_id = st.session_state.active_document
    document_title = get_document_title(document_id)
    
    st.title(f"Document: {document_title}")
    
    tab1, tab2, tab3 = st.tabs(["Flashcards", "Quiz", "Document Content"])
    
    with tab1:
        st.subheader("Flashcards")
        flashcards = get_document_flashcards(document_id)
        
        if flashcards:
            # Add download button for flashcards PDF
            pdf_bytes = generate_flashcards_pdf(flashcards, document_title)
            st.download_button(
                label="Download Flashcards as PDF",
                data=pdf_bytes,
                file_name=f"flashcards_{document_title.replace(' ', '_')}.pdf",
                mime="application/pdf",
            )
            
            for i, card in enumerate(flashcards):
                with st.expander(f"Flashcard {i+1}: {card['front']}"):
                    st.write(card['back'])
        else:
            st.info("No flashcards found for this document.")
            
            if st.button("Generate Flashcards"):
                with st.spinner("Generating flashcards..."):
                    content = get_document_content(document_id)
                    new_flashcards = generate_flashcards(document_id, content)
                    
                    if new_flashcards:
                        st.success(f"Generated {len(new_flashcards)} flashcards!")
                        st.rerun()
                    else:
                        st.error("Failed to generate flashcards.")
    
    with tab2:
        st.subheader("Quiz")
        
        if st.button("Generate New Quiz"):
            with st.spinner("Creating quiz..."):
                content = get_document_content(document_id)
                quiz_id = generate_quiz(document_id, st.session_state.user_id, content)
                
                if quiz_id:
                    st.session_state.active_page = "take_quiz"
                    st.session_state.active_quiz = quiz_id
                    st.rerun()
                else:
                    st.error("Failed to generate quiz.")
    
    with tab3:
        st.subheader("Document Content")
        content = get_document_content(document_id)
        st.text_area("Document Text", content, height=400)

def render_flashcards_page():
    st.title("My Flashcards")
    
    documents = get_user_documents(st.session_state.user_id)
    
    if not documents:
        st.info("You haven't uploaded any documents yet. Go to 'Upload Document' to get started!")
        return
    
    for doc in documents:
        flashcards = get_document_flashcards(doc['id'])
        
        if flashcards:
            st.subheader(f"📚 {doc['title']} ({len(flashcards)} flashcards)")
            
            # Add download button for flashcards PDF
            pdf_bytes = generate_flashcards_pdf(flashcards, doc['title'])
            st.download_button(
                label="Download Flashcards as PDF",
                data=pdf_bytes,
                file_name=f"flashcards_{doc['title'].replace(' ', '_')}.pdf",
                mime="application/pdf",
            )
            
            # Ensure `st.expander()` is not inside another `st.expander()` or improper container
            for i, card in enumerate(flashcards):
                expander = st.expander(f"Flashcard {i+1}: {card['front']}")
                with expander:
                    st.write(card['back'])

def render_quizzes_page():
    st.title("My Quizzes")
    
    quizzes = get_user_quizzes(st.session_state.user_id)
    
    if not quizzes:
        st.info("You haven't created any quizzes yet.")
        
        # Show documents to create quizzes from
        st.subheader("Create a Quiz from Document")
        documents = get_user_documents(st.session_state.user_id)
        
        if documents:
            for doc in documents:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"📚 {doc['title']}")
                with col2:
                    if st.button("Create Quiz", key=f"quiz_{doc['id']}"):
                        with st.spinner("Creating quiz..."):
                            content = get_document_content(doc['id'])
                            quiz_id = generate_quiz(doc['id'], st.session_state.user_id, content)
                            
                            if quiz_id:
                                st.session_state.active_page = "take_quiz"
                                st.session_state.active_quiz = quiz_id
                                st.rerun()
                            else:
                                st.error("Failed to generate quiz.")
        else:
            st.info("You haven't uploaded any documents yet. Go to 'Upload Document' to get started!")
    else:
        for quiz in quizzes:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"📝 {quiz['title']} ({quiz['document_title']})")
            with col2:
                if st.button("Take Quiz", key=f"take_{quiz['id']}"):
                    st.session_state.active_page = "take_quiz"
                    st.session_state.active_quiz = quiz['id']
                    st.session_state.current_question = 0
                    st.session_state.user_answers = {}
                    st.session_state.quiz_completed = False
                    st.session_state.quiz_score = 0
                    st.rerun()

def render_take_quiz_page():
    if not st.session_state.active_quiz:
        st.error("No quiz selected")
        return
    
    quiz_id = st.session_state.active_quiz
    
    # Check if quiz questions are already loaded
    if st.session_state.quiz_questions is None:
        questions = get_quiz_questions(quiz_id)
        st.session_state.quiz_questions = shuffle_options(questions)
    
    questions = st.session_state.quiz_questions
    
    if not questions:
        st.error("No questions found for this quiz")
        return
    
    if st.session_state.quiz_completed:
        # Show quiz results
        st.title("Quiz Results")
        
        score = st.session_state.quiz_score
        total = len(questions)
        percentage = (score / total) * 100
        
        st.markdown(f"## Your Score: {score}/{total} ({percentage:.1f}%)")
        
        # Save quiz result to database
        save_quiz_result(quiz_id, st.session_state.user_id, score, total)
        
        # Show correct/incorrect answers
        for i, q in enumerate(questions):
            user_answer = st.session_state.user_answers.get(q["id"])
            correct = user_answer == q["correct_answer"]
            
            with st.container():
                if correct:
                    st.success(f"Question {i+1}: {q['question_text']}")
                else:
                    st.error(f"Question {i+1}: {q['question_text']}")
                
                st.write(f"Your answer: {user_answer}")
                
                if not correct:
                    st.write(f"Correct answer: {q['correct_answer']}")
                
                st.markdown("---")
        
        if st.button("Return to Quizzes"):
            st.session_state.active_page = "quizzes"
            st.session_state.active_quiz = None
            st.session_state.quiz_questions = None
            st.rerun()
        
    else:
        # Show current question
        current_idx = st.session_state.current_question
        
        if current_idx < len(questions):
            current_q = questions[current_idx]
            
            st.title(f"Question {current_idx + 1} of {len(questions)}")
            st.subheader(current_q["question_text"])
            
            # Display options
            user_choice = st.radio(
                "Select your answer:",
                current_q["options"],
                key=f"q_{current_idx}"
            )
            
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("Submit Answer"):
                    # Save the answer
                    st.session_state.user_answers[current_q["id"]] = user_choice
                    
                    # Check if correct
                    if user_choice == current_q["correct_answer"]:
                        st.session_state.quiz_score += 1
                    
                    # Move to next question
                    st.session_state.current_question += 1
                    
                    # Check if quiz is complete
                    if st.session_state.current_question >= len(questions):
                        st.session_state.quiz_completed = True
                    
                    st.rerun()
            
            # Progress bar
            progress = (current_idx / len(questions))
            st.progress(progress)
            
        else:
            st.session_state.quiz_completed = True
            st.rerun()

def render_progress_page():
    st.title("Progress Report")
    
    progress = get_user_progress(st.session_state.user_id)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Quizzes Taken", progress["total_attempts"])
    
    with col2:
        st.metric("Questions Answered", progress["total_questions"])
    
    with col3:
        st.metric("Average Score", f"{progress['average_score']}%")
    
    # Progress chart
    if progress["attempts"]:
        # Convert data for chart
        df = pd.DataFrame(progress["attempts"])
        df['date'] = pd.to_datetime(df['date'])
        
        # Create chart
        fig = px.line(
            df, 
            x='date', 
            y='score', 
            title='Quiz Scores Over Time',
            labels={'date': 'Date', 'score': 'Score (%)'},
            markers=True
        )
        
        st.plotly_chart(fig)
    else:
        st.info("Take some quizzes to see your progress over time!")

def main():
    # Initialize database
    init_db()
    
    # Initialize session state
    init_session_state()
    
    # Page routing
    if st.session_state.user_id:
        # User is logged in
        render_sidebar()
        
        if check_session_validity():
            # Show appropriate page
            if st.session_state.active_page == "dashboard":
                render_dashboard()
            elif st.session_state.active_page == "upload":
                render_upload_page()
            elif st.session_state.active_page == "document":
                render_document_page()
            elif st.session_state.active_page == "flashcards":
                render_flashcards_page()
            elif st.session_state.active_page == "quizzes":
                render_quizzes_page()
            elif st.session_state.active_page == "take_quiz":
                render_take_quiz_page()
            elif st.session_state.active_page == "progress":
                render_progress_page()
        else:
            render_login_page()
    else:
        # User is not logged in
        render_login_page()

if __name__ == "__main__":
    main()