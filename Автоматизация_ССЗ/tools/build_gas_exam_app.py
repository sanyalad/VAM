import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMS_DIR = ROOT / "data" / "exams"
OUT_DIR = ROOT / "google_apps_script"

eb3_path = EXAMS_DIR / "eb_group3.json"
ptb_path = EXAMS_DIR / "eb_ptb.json"

with open(eb3_path, encoding="utf-8") as f:
    eb3_data = json.load(f)

with open(ptb_path, encoding="utf-8") as f:
    ptb_data = json.load(f)

exam_db = {
    "eb_group3": eb3_data,
    "eb_ptb": ptb_data
}

json_str = json.dumps(exam_db, ensure_ascii=False)

code_gs_content = """// Google Apps Script — Серверный код тренажёра Электробезопасности и ПТБ
// Инструкция по деплою:
// 1. Перейдите на https://script.google.com/
// 2. Создайте новый проект "Тренажёр ЭБ и ПТБ"
// 3. Вставьте этот код в файл Code.gs
// 4. Создайте HTML-файл с именем "Index" и вставьте содержимое Index_Exam.html
// 5. Нажмите "Начало развертывания" (Deploy) -> "Новое развертывание" -> "Веб-приложение"
// 6. Установите "У кого есть доступ": "Все" (Anyone)
// 7. Скопируйте ссылку и используйте на любом устройстве!

function doGet(e) {
  var template = HtmlService.createTemplateFromFile('Index');
  return template.evaluate()
    .setTitle('Тренажёр ЭБ и ПТБ — ВАМ')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function getExamDB() {
  return """ + json_str + """;
}

// Опциональное логирование результатов в Google Таблицу (укажите ID таблицы ниже, если хотите вести логи на сервере)
var LOG_SPREADSHEET_ID = ""; // Например: '17crPE60eITsnUBJT9LWdN-HIJ5p6Zfd5fHBUTBShcAo'

function logExamResult(data) {
  try {
    if (!LOG_SPREADSHEET_ID) return { success: true, note: "Local storage only" };
    var ss = SpreadsheetApp.openById(LOG_SPREADSHEET_ID);
    var sheet = ss.getSheetByName("Логи экзаменов") || ss.insertSheet("Логи экзаменов");
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(["Дата и время", "ФИО / Работник", "Экзамен", "Билет / Режим", "Результат", "Ошибки (IDs)"]);
    }
    sheet.appendRow([
      new Date().toLocaleString("ru-RU"),
      data.userName || "Аноним",
      data.examTitle || data.examId,
      data.ticketTitle || "Билет " + data.ticketId,
      data.score + " / " + data.total + " (" + (data.passed ? "СДАН" : "НЕ СДАН") + ")",
      JSON.stringify(data.errorQuestions || [])
    ]);
    return { success: true };
  } catch (e) {
    return { success: false, error: e.toString() };
  }
}
"""

with open(OUT_DIR / "Code_Exam.gs", "w", encoding="utf-8") as f:
    f.write(code_gs_content)

html_template = """<!DOCTYPE html>
<html lang="ru">
<head>
  <base target="_top">
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <title>Тренажёр ЭБ и ПТБ — ВАМ</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-dark: #1e1e1e;
      --card-bg: #252526;
      --card-hover: #2d2d30;
      --accent-blue: #007acc;
      --accent-indigo: #005a9e;
      --accent-amber: #d7ba7d;
      --success-green: #4CAF50;
      --success-bg: rgba(76, 175, 80, 0.15);
      --error-red: #d16969;
      --error-bg: rgba(209, 105, 105, 0.15);
      --text-main: #d4d4d4;
      --text-muted: #94a3b8;
      --border-color: #3e3e42;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      -webkit-tap-highlight-color: transparent;
    }

    body {
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      background-color: var(--bg-dark);
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      user-select: none;
    }

    header {
      background: var(--card-bg);
      border-bottom: 1px solid var(--border-color);
      padding: 14px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 100;
      box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .brand-logo {
      width: 36px;
      height: 36px;
      background: linear-gradient(135deg, var(--accent-blue), var(--accent-indigo));
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      font-size: 1.2rem;
      color: white;
      box-shadow: 0 0 15px rgba(56, 189, 248, 0.4);
    }

    .brand-text h1 {
      font-size: 1.05rem;
      font-weight: 700;
      color: var(--text-main);
    }

    .brand-text p {
      font-size: 0.75rem;
      color: var(--text-muted);
    }

    .user-badge {
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid var(--border-color);
      padding: 6px 12px;
      border-radius: 20px;
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--accent-blue);
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .container {
      max-width: 720px;
      width: 100%;
      margin: 0 auto;
      padding: 16px;
      flex: 1;
      display: flex;
      flex-direction: column;
    }

    .screen {
      display: none;
      flex-direction: column;
      gap: 16px;
      width: 100%;
    }

    .screen.active {
      display: flex;
    }

    /* CARD STYLES */
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }

    .card-title {
      font-size: 1.15rem;
      font-weight: 700;
      margin-bottom: 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    /* INPUTS */
    .form-input {
      width: 100%;
      padding: 14px 16px;
      background: var(--bg-dark);
      border: 1.5px solid var(--border-color);
      border-radius: 12px;
      color: var(--text-main);
      font-size: 1rem;
      outline: none;
      margin-bottom: 14px;
    }

    .form-input:focus {
      border-color: var(--accent-blue);
    }

    /* BUTTONS */
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 14px 20px;
      border-radius: 12px;
      font-size: 1rem;
      font-weight: 600;
      border: none;
      cursor: pointer;
      transition: all 0.15s ease;
      width: 100%;
      text-align: center;
    }

    .btn-primary {
      background: var(--accent-blue);
      color: white;
    }

    .btn-amber {
      background: var(--accent-amber);
      color: #1e1e1e;
    }

    .btn-primary:active, .btn-amber:active {
      transform: scale(0.98);
    }

    .btn-outline {
      background: transparent;
      border: 1px solid var(--border-color);
      color: var(--text-main);
    }

    .btn-outline:active {
      background: var(--card-hover);
    }

    /* MODE SELECTOR */
    .exam-selector {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .exam-opt {
      background: var(--card-bg);
      border: 2px solid var(--border-color);
      border-radius: 14px;
      padding: 16px;
      cursor: pointer;
      transition: all 0.2s ease;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .exam-opt.selected {
      border-color: var(--accent-blue);
      background: rgba(56, 189, 248, 0.08);
    }

    .exam-opt-info h3 {
      font-size: 1.05rem;
      font-weight: 600;
      color: var(--text-main);
    }

    .exam-opt-info p {
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: 4px;
    }

    /* TICKET GRID */
    .ticket-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(65px, 1fr));
      gap: 10px;
      margin-top: 12px;
    }

    .ticket-btn {
      height: 54px;
      background: var(--card-bg);
      border: 1.5px solid var(--border-color);
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 1.1rem;
      color: var(--text-main);
      cursor: pointer;
      transition: all 0.15s ease;
    }

    .ticket-btn:active {
      transform: scale(0.95);
    }

    .ticket-btn.passed {
      border-color: var(--success-green);
      background: var(--success-bg);
      color: var(--success-green);
    }

    .ticket-btn.failed {
      border-color: var(--error-red);
      background: var(--error-bg);
      color: var(--error-red);
    }

    /* QUIZ VIEW */
    .quiz-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }

    .timer-badge {
      background: rgba(239, 68, 68, 0.2);
      color: #fca5a5;
      padding: 6px 12px;
      border-radius: 20px;
      font-weight: 700;
      font-size: 0.9rem;
      border: 1px solid rgba(239, 68, 68, 0.4);
    }

    .progress-bar-wrap {
      width: 100%;
      height: 8px;
      background: var(--card-bg);
      border-radius: 4px;
      overflow: hidden;
      margin: 4px 0;
    }

    .progress-bar-fill {
      height: 100%;
      background: var(--accent-blue);
      width: 0%;
      transition: width 0.3s ease;
    }

    .q-number {
      font-size: 0.85rem;
      color: var(--accent-blue);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    .q-text {
      font-size: 1.05rem;
      font-weight: 600;
      line-height: 1.45;
      margin-top: 6px;
    }

    .options-list {
      display: flex;
      flex-direction: column;
      gap: 12px;
      margin-top: 16px;
    }

    .option-btn {
      background: var(--card-bg);
      border: 1.5px solid var(--border-color);
      border-radius: 12px;
      padding: 14px 16px;
      text-align: left;
      font-size: 0.95rem;
      line-height: 1.4;
      color: var(--text-main);
      cursor: pointer;
      transition: all 0.15s ease;
      display: flex;
      gap: 12px;
      align-items: flex-start;
    }

    .option-num {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background: rgba(255,255,255,0.08);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.8rem;
      font-weight: 700;
      flex-shrink: 0;
      margin-top: 1px;
    }

    .option-btn:active:not(.disabled) {
      transform: scale(0.99);
      border-color: var(--accent-blue);
    }

    .option-btn.correct {
      border-color: var(--success-green) !important;
      background: var(--success-bg) !important;
      color: #6ee7b7 !important;
    }

    .option-btn.correct .option-num {
      background: var(--success-green);
      color: white;
    }

    .option-btn.wrong {
      border-color: var(--error-red) !important;
      background: var(--error-bg) !important;
      color: #fca5a5 !important;
    }

    .option-btn.wrong .option-num {
      background: var(--error-red);
      color: white;
    }

    .option-btn.selected {
      border-color: var(--accent-blue) !important;
      background: rgba(56, 189, 248, 0.1) !important;
    }

    .option-btn.selected .option-num {
      background: var(--accent-blue);
      color: #0f172a;
    }

    .open-answer-box {
      background: rgba(16, 185, 129, 0.1);
      border: 1px solid var(--success-green);
      border-radius: 12px;
      padding: 16px;
      margin-top: 16px;
      display: none;
    }

    .open-answer-box h4 {
      color: var(--success-green);
      font-size: 0.95rem;
      margin-bottom: 8px;
    }

    .open-answer-text {
      white-space: pre-wrap;
      font-size: 0.95rem;
      line-height: 1.5;
      color: #d1fae5;
    }

    .quiz-nav {
      display: flex;
      gap: 12px;
      margin-top: auto;
      padding-top: 16px;
    }

    /* RESULT MODAL / SCREEN */
    .result-card {
      text-align: center;
      padding: 32px 20px;
    }

    .result-score {
      font-size: 2.2rem;
      font-weight: 800;
      margin: 8px 0;
    }

    .result-msg {
      color: var(--text-muted);
      font-size: 1rem;
      margin-bottom: 24px;
    }

    .tab-bar {
      display: flex;
      background: var(--card-bg);
      border-radius: 12px;
      padding: 4px;
      border: 1px solid var(--border-color);
      margin-bottom: 12px;
    }

    .tab-btn {
      flex: 1;
      padding: 10px;
      text-align: center;
      font-weight: 600;
      font-size: 0.9rem;
      border-radius: 8px;
      border: none;
      background: transparent;
      color: var(--text-muted);
      cursor: pointer;
    }

    .tab-btn.active {
      background: var(--accent-blue);
      color: #0f172a;
    }
  </style>
</head>
<body>

  <header>
    <div class="brand">
      <div class="brand-logo">ЭБ</div>
      <div class="brand-text">
        <h1>Тренажёр ЭБ и ПТБ</h1>
        <p>Подготовка к экзамену ВАМ</p>
      </div>
    </div>
    <div id="userBadge" class="user-badge" onclick="showAuthScreen()">
      <span id="userNameDisplay">Пользователь: Гость</span>
    </div>
  </header>

  <div class="container">
    
    <!-- 0. AUTH SCREEN -->
    <div id="authScreen" class="screen">
      <div class="card" style="text-align:center; padding: 28px 20px;">
        <h2 style="font-size: 1.4rem; font-weight: 700; margin-bottom: 8px;">Авторизация работника</h2>
        <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 20px;">
          Введите ваше ФИО или табельный номер, чтобы сохранять свои результаты и отрабатывать личные ошибки при выходе.
        </p>
        <input type="text" id="userNameInput" class="form-input" placeholder="Например: Иванов И.И. (Цех 47)" />
        <button class="btn btn-primary" onclick="saveUserAuth()">Войти и начать</button>
      </div>
    </div>

    <!-- 1. HOME / SELECTION SCREEN -->
    <div id="homeScreen" class="screen active">
      <!-- WORK ON MISTAKES BANNER -->
      <div id="mistakesCard" class="card" style="display:none; border-color: var(--accent-amber); background: rgba(215, 186, 125, 0.08);">
        <div class="card-title" style="color: var(--accent-amber);">
          <span>Работа над ошибками</span>
          <span id="mistakesBadge" style="font-size:0.85rem; background:var(--accent-amber); color:#0f172a; padding:3px 8px; border-radius:12px;">0 вопросов</span>
        </div>
        <p style="font-size:0.85rem; color:var(--text-muted); margin-bottom:14px;">
          Здесь собраны вопросы, в которых вы допускали ошибки. Ответьте правильно, чтобы убрать вопрос из списка ошибок!
        </p>
        <button class="btn btn-amber" onclick="startMistakesMode()">Прорешать ошибки</button>
      </div>

      <div class="card">
        <div class="card-title">Выберите категорию</div>
        <div class="exam-selector">
          <div id="opt_eb3" class="exam-opt selected" onclick="selectExam('eb_group3', this)">
            <div class="exam-opt-info">
              <h3>Электробезопасность — III группа</h3>
              <p>30 билетов по 10 вопросов (Выбор ответа)</p>
            </div>
            <span style="font-size: 1.2rem;">→</span>
          </div>
          <div id="opt_ptb" class="exam-opt" onclick="selectExam('eb_ptb', this)">
            <div class="exam-opt-info">
              <h3>ПТБ — Билеты</h3>
              <p>Открытые вопросы с готовыми правильными ответами</p>
            </div>
            <span style="font-size: 1.2rem;">→</span>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Режим прохождения</div>
        <div class="tab-bar">
          <button id="btnModeStudy" class="tab-btn active" onclick="setMode('study', this)">Обучение</button>
          <button id="btnModeExam" class="tab-btn" onclick="setMode('exam', this)">Экзамен</button>
        </div>
        <p id="modeDesc" style="font-size:0.85rem; color:var(--text-muted); margin-bottom:16px;">
          Показывает подсказку и верный ответ сразу после клика. Без ограничений по времени.
        </p>

        <button class="btn btn-primary" onclick="startRandomTicket()">Случайный билет</button>
      </div>

      <div class="card">
        <div class="card-title">
          <span>Все билеты</span>
          <span id="statSummary" style="font-size:0.8rem; color:var(--text-muted); font-weight:normal;"></span>
        </div>
        <div id="ticketGrid" class="ticket-grid"></div>
      </div>
    </div>

    <!-- 2. QUIZ SCREEN -->
    <div id="quizScreen" class="screen">
      <div class="quiz-header">
        <button class="btn btn-outline" style="width:auto; padding:8px 14px;" onclick="confirmExit()">✕ Выход</button>
        <span id="ticketTitle" style="font-weight:700;">Билет № 1</span>
        <div id="timerBadge" class="timer-badge" style="display:none;">19:59</div>
      </div>

      <div class="progress-bar-wrap">
        <div id="progressBar" class="progress-bar-fill"></div>
      </div>

      <div class="card" style="flex:1; display:flex; flex-direction:column;">
        <div id="qNumText" class="q-number">Вопрос 1 из 10</div>
        <div id="qText" class="q-text">Текст вопроса...</div>

        <!-- Options for Choice Questions -->
        <div id="optionsList" class="options-list"></div>

        <!-- Open Answer Box for PTB -->
        <div id="openAnswerBox" class="open-answer-box">
          <h4>Правильный ответ (ПТБ):</h4>
          <div id="openAnswerText" class="open-answer-text"></div>
        </div>
      </div>

      <div class="quiz-nav">
        <button id="btnPrev" class="btn btn-outline" onclick="prevQuestion()" style="flex:1;">← Назад</button>
        <button id="btnNext" class="btn btn-primary" onclick="nextQuestion()" style="flex:1;">Далее →</button>
      </div>
    </div>

    <!-- 3. RESULT SCREEN -->
    <div id="resultScreen" class="screen">
      <div class="card result-card">
        <h2 id="resTitle" style="font-size:1.6rem; font-weight:800;">Экзамен сдан!</h2>
        <div id="resScore" class="result-score">10 / 10</div>
        <p id="resMsg" class="result-msg">Отличный результат, ошибок нет!</p>

        <button class="btn btn-primary" onclick="showHomeScreen()">К выбору билетов</button>
      </div>
    </div>

  </div>

  <script>
    // Embedded Exam Database
    var EXAM_DB = __EXAM_DB_JSON__;

    var currentUser = localStorage.getItem('exam_user_name') || '';
    var currentExamId = 'eb_group3';
    var currentMode = 'study'; // 'study', 'exam', 'mistakes'
    var currentTicket = null;
    var currentQIndex = 0;
    var userAnswers = {}; // qIndex -> optionNum
    var timerInterval = null;
    var timeLeft = 1200; // 20 mins

    window.addEventListener('DOMContentLoaded', function() {
      if (!currentUser) {
        showAuthScreen();
      } else {
        updateUserBadge();
      }

      if (typeof google !== 'undefined' && google.script && google.script.run) {
        google.script.run.withSuccessHandler(function(db) {
          if (db) {
            EXAM_DB = db;
            renderTicketGrid();
            checkMistakesPool();
          }
        }).getExamDB();
      }
      renderTicketGrid();
      checkMistakesPool();
    });

    function showAuthScreen() {
      document.getElementById('userNameInput').value = currentUser;
      showScreen('authScreen');
    }

    function saveUserAuth() {
      var val = document.getElementById('userNameInput').value.trim();
      if (!val) {
        alert('Пожалуйста, введите ваше ФИО или имя.');
        return;
      }
      currentUser = val;
      localStorage.setItem('exam_user_name', currentUser);
      updateUserBadge();
      showHomeScreen();
    }

    function updateUserBadge() {
      var badge = document.getElementById('userNameDisplay');
      if (badge) badge.innerText = 'Пользователь: ' + (currentUser || 'Гость');
    }

    function selectExam(id, el) {
      currentExamId = id;
      document.querySelectorAll('.exam-opt').forEach(function(opt) { opt.classList.remove('selected'); });
      if (el) el.classList.add('selected');
      renderTicketGrid();
      checkMistakesPool();
    }

    function setMode(mode, el) {
      currentMode = mode;
      document.querySelectorAll('.tab-btn').forEach(function(btn) { btn.classList.remove('active'); });
      if (el) el.classList.add('active');

      var desc = document.getElementById('modeDesc');
      if (mode === 'study') {
        desc.innerText = 'Показывает верный ответ сразу после клика. Без ограничений по времени.';
      } else {
        desc.innerText = 'Режим экзамена: 20 минут, результат показывается после ответов на все вопросы.';
      }
    }

    function getMistakesKey() {
      return 'exam_mistakes_' + (currentUser || 'guest') + '_' + currentExamId;
    }

    function getMistakesPool() {
      try {
        return JSON.parse(localStorage.getItem(getMistakesKey()) || '[]');
      } catch (e) {
        return [];
      }
    }

    function saveMistakesPool(pool) {
      try {
        localStorage.setItem(getMistakesKey(), JSON.stringify(pool));
      } catch (e) {}
      checkMistakesPool();
    }

    function addMistake(qUid, questionObj, ticketId, correctAns) {
      var pool = getMistakesPool();
      var exists = pool.find(function(item) { return item.uid === qUid; });
      if (!exists) {
        pool.push({
          uid: qUid,
          ticketId: ticketId,
          correctAns: correctAns || questionObj._correctAns || 1,
          q: questionObj
        });
        saveMistakesPool(pool);
      }
    }

    function removeMistake(qUid) {
      var pool = getMistakesPool();
      pool = pool.filter(function(item) { return item.uid !== qUid; });
      saveMistakesPool(pool);
    }

    function checkMistakesPool() {
      var card = document.getElementById('mistakesCard');
      var badge = document.getElementById('mistakesBadge');
      var pool = getMistakesPool();

      if (pool.length > 0) {
        if (card) card.style.display = 'block';
        if (badge) badge.innerText = pool.length + ' ' + (pool.length === 1 ? 'вопрос' : (pool.length < 5 ? 'вопроса' : 'вопросов'));
      } else {
        if (card) card.style.display = 'none';
      }
    }

    function startMistakesMode() {
      var pool = getMistakesPool();
      if (pool.length === 0) return;

      currentMode = 'mistakes';
      var questions = [];
      var answers = [];

      pool.forEach(function(item) {
        var qCopy = JSON.parse(JSON.stringify(item.q));
        qCopy._uid = item.uid;
        qCopy._correctAns = item.correctAns || item.q._correctAns || 1;
        questions.push(qCopy);
        answers.push(qCopy._correctAns);
      });

      currentTicket = {
        id: 'mistakes',
        title: 'Работа над ошибками',
        questions: questions,
        answers: answers
      };

      currentQIndex = 0;
      userAnswers = {};

      document.getElementById('ticketTitle').innerText = currentTicket.title;
      document.getElementById('timerBadge').style.display = 'none';
      showScreen('quizScreen');
      renderQuestion();
    }

    function renderTicketGrid() {
      var grid = document.getElementById('ticketGrid');
      if (!grid) return;
      grid.innerHTML = '';
      if (!EXAM_DB || !EXAM_DB[currentExamId]) return;

      var tickets = EXAM_DB[currentExamId].tickets || [];
      var history = {};
      try {
        history = JSON.parse(localStorage.getItem('exam_stats_' + (currentUser || 'guest') + '_' + currentExamId) || '{}');
      } catch (e) {}

      var passedCount = 0;

      tickets.forEach(function(t) {
        var btn = document.createElement('div');
        btn.className = 'ticket-btn';
        if (history[t.id]) {
          if (history[t.id].passed) {
            btn.classList.add('passed');
            passedCount++;
          } else {
            btn.classList.add('failed');
          }
        }
        btn.innerText = t.id;
        btn.onclick = function() { startTicket(t.id); };
        grid.appendChild(btn);
      });

      var statSummary = document.getElementById('statSummary');
      if (statSummary) {
        statSummary.innerText = 'Сдано: ' + passedCount + ' из ' + tickets.length;
      }
    }

    function startRandomTicket() {
      if (!EXAM_DB || !EXAM_DB[currentExamId]) return;
      var tickets = EXAM_DB[currentExamId].tickets || [];
      if (tickets.length === 0) return;
      var randomTid = tickets[Math.floor(Math.random() * tickets.length)].id;
      startTicket(randomTid);
    }

    function startTicket(tid) {
      if (!EXAM_DB || !EXAM_DB[currentExamId]) return;
      var tickets = EXAM_DB[currentExamId].tickets || [];
      currentTicket = tickets.find(function(t) { return t.id === tid; });
      if (!currentTicket) return;

      currentQIndex = 0;
      userAnswers = {};

      document.getElementById('ticketTitle').innerText = currentTicket.title || ('Билет № ' + tid);
      showScreen('quizScreen');

      if (currentMode === 'exam') {
        startTimer();
      } else {
        document.getElementById('timerBadge').style.display = 'none';
      }

      renderQuestion();
    }

    function startTimer() {
      timeLeft = 1200;
      var badge = document.getElementById('timerBadge');
      badge.style.display = 'block';
      
      clearInterval(timerInterval);
      timerInterval = setInterval(function() {
        timeLeft--;
        var m = Math.floor(timeLeft / 60);
        var s = timeLeft % 60;
        badge.innerText = m + ':' + (s < 10 ? '0' : '') + s;
        if (timeLeft <= 0) {
          clearInterval(timerInterval);
          finishQuiz();
        }
      }, 1000);
    }

    function renderQuestion() {
      if (!currentTicket) return;
      var q = currentTicket.questions[currentQIndex];
      var total = currentTicket.questions.length;

      document.getElementById('qNumText').innerText = 'Вопрос ' + (currentQIndex + 1) + ' из ' + total;
      document.getElementById('qText').innerText = q.text;
      document.getElementById('progressBar').style.width = (((currentQIndex + 1) / total) * 100) + '%';

      var optionsList = document.getElementById('optionsList');
      var openAnswerBox = document.getElementById('openAnswerBox');

      optionsList.innerHTML = '';
      openAnswerBox.style.display = 'none';

      var isPtB = currentExamId === 'eb_ptb' || !q.options || q.options.length === 0;

      if (isPtB) {
        openAnswerBox.style.display = 'block';
        document.getElementById('openAnswerText').innerText = q.answer_text || 'Текст ответа отсутствует.';
      } else {
        var correctAns = (currentTicket.answers && currentTicket.answers.length > currentQIndex) ? currentTicket.answers[currentQIndex] : null;
        q._correctAns = correctAns;
        var qUid = q._uid || (currentExamId + '_T' + (currentTicket.id || 'x') + '_Q' + q.num);
        q._uid = qUid;
        var userSel = userAnswers[currentQIndex];

        q.options.forEach(function(o) {
          var btn = document.createElement('button');
          btn.className = 'option-btn';
          
          if (userSel !== undefined) {
            if (currentMode === 'study' || currentMode === 'mistakes') {
              btn.classList.add('disabled');
              if (o.num === correctAns) btn.classList.add('correct');
              else if (o.num === userSel && userSel !== correctAns) btn.classList.add('wrong');
            } else {
              if (o.num === userSel) btn.classList.add('selected');
            }
          }

          btn.innerHTML = '<div class="option-num">' + o.num + '</div><div>' + o.text + '</div>';
          btn.onclick = function() { selectOption(o.num); };
          optionsList.appendChild(btn);
        });
      }

      document.getElementById('btnPrev').style.visibility = currentQIndex === 0 ? 'hidden' : 'visible';
      var btnNext = document.getElementById('btnNext');
      if (currentQIndex === total - 1) {
        btnNext.innerText = 'Завершить';
      } else {
        btnNext.innerText = 'Далее →';
      }
    }

    function selectOption(num) {
      if (userAnswers[currentQIndex] !== undefined && (currentMode === 'study' || currentMode === 'mistakes')) return;
      userAnswers[currentQIndex] = num;
      
      var q = currentTicket.questions[currentQIndex];
      var correctAns = (currentTicket.answers && currentTicket.answers.length > currentQIndex) ? currentTicket.answers[currentQIndex] : (q._correctAns || null);
      var qUid = q._uid || (currentExamId + '_T' + (currentTicket.id || 'x') + '_Q' + q.num);

      if (num !== correctAns) {
        addMistake(qUid, q, currentTicket.id, correctAns);
      } else if (currentMode === 'mistakes') {
        removeMistake(qUid);
      }

      renderQuestion();
    }

    function nextQuestion() {
      var total = currentTicket.questions.length;
      if (currentQIndex < total - 1) {
        currentQIndex++;
        renderQuestion();
      } else {
        finishQuiz();
      }
    }

    function prevQuestion() {
      if (currentQIndex > 0) {
        currentQIndex--;
        renderQuestion();
      }
    }

    function finishQuiz() {
      clearInterval(timerInterval);
      if (!currentTicket) return;

      var correctCount = 0;
      var total = currentTicket.questions.length;
      var answers = currentTicket.answers || [];
      var errorList = [];

      currentTicket.questions.forEach(function(q, idx) {
        var correctAns = answers[idx];
        var qUid = q._uid || (currentExamId + '_T' + (currentTicket.id || 'x') + '_Q' + q.num);
        if (userAnswers[idx] === correctAns) {
          correctCount++;
          removeMistake(qUid);
        } else {
          errorList.push(q.num);
          addMistake(qUid, q, currentTicket.id, correctAns);
        }
      });

      var passed = correctCount >= total - 2;

      // Save to localStorage
      try {
        var userStatsKey = 'exam_stats_' + (currentUser || 'guest') + '_' + currentExamId;
        var history = JSON.parse(localStorage.getItem(userStatsKey) || '{}');
        history[currentTicket.id] = { passed: passed, score: correctCount, total: total };
        localStorage.setItem(userStatsKey, JSON.stringify(history));
      } catch (e) {}

      // Log result to Google Script backend if connected
      if (typeof google !== 'undefined' && google.script && google.script.run) {
        google.script.run.logExamResult({
          userName: currentUser,
          examId: currentExamId,
          examTitle: currentExamId === 'eb_group3' ? 'Электробезопасность III' : 'ПТБ',
          ticketId: currentTicket.id,
          ticketTitle: currentTicket.title,
          score: correctCount,
          total: total,
          passed: passed,
          errorQuestions: errorList
        });
      }

      var resTitle = document.getElementById('resTitle');
      if (resTitle) resTitle.innerText = passed ? 'Экзамен сдан!' : 'Экзамен не сдан!';
      
      document.getElementById('resScore').innerText = correctCount + ' / ' + total;
      document.getElementById('resMsg').innerText = passed
        ? 'Отличный результат, норматив выполнен!'
        : 'Допущено более 2 ошибок. Попробуйте еще раз в режиме «Работа над ошибками».';

      showScreen('resultScreen');
    }

    function confirmExit() {
      if (confirm('Вы действительно хотите выйти из билета?')) {
        clearInterval(timerInterval);
        showHomeScreen();
      }
    }

    function showHomeScreen() {
      renderTicketGrid();
      checkMistakesPool();
      showScreen('homeScreen');
    }

    function showScreen(id) {
      document.querySelectorAll('.screen').forEach(function(s) { s.classList.remove('active'); });
      var sc = document.getElementById(id);
      if (sc) sc.classList.add('active');
    }
  </script>
</body>
</html>
"""

html_final = html_template.replace("__EXAM_DB_JSON__", json_str)

with open(OUT_DIR / "Index_Exam.html", "w", encoding="utf-8") as f:
    f.write(html_final)

print("Generated upgraded Index_Exam.html and Code_Exam.gs successfully!")
