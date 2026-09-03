const SPREADSHEET_ID = '17crPE60eITsnUBJT9LWdN-HIJ5p6Zfd5fHBUTBShcAo';
const FOLDER_ID = '1PLIRbU-yE78wC7Ap_5PBfdgljnwLCFlX';
const GEMINI_API_KEY = 'ВСТАВЬТЕ_СЮДА_ВАШ_КЛЮЧ_GEMINI'; // Получить на https://aistudio.google.com/

function doGet(e) {
  // Если пришел запрос от десктопного приложения на получение заметок
  if (e && e.parameter.action === 'get_notes') {
    return ContentService.createTextOutput(JSON.stringify(getLatestNotes()))
      .setMimeType(ContentService.MimeType.JSON);
  }
  
  // Иначе отдаем веб-страницу
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('План / Заметки')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function doPost(e) {
  try {
    let text = e.parameter.text || '';
    let fileData = e.parameter.file;
    let fileName = e.parameter.fileName;
    let fileUrl = '';
    
    // 1. Пропускаем текст через Gemini, если он есть
    let processedText = text;
    if (text && GEMINI_API_KEY !== 'ВСТАВЬТЕ_СЮДА_ВАШ_КЛЮЧ_GEMINI') {
      processedText = processWithGemini(text);
    }
    
    // 2. Сохраняем файл на Диск, если он есть
    if (fileData && fileName) {
      const folder = DriveApp.getFolderById(FOLDER_ID);
      const contentType = fileData.substring(5,fileData.indexOf(';')),
            bytes = Utilities.base64Decode(fileData.substr(fileData.indexOf('base64,')+7)),
            blob = Utilities.newBlob(bytes, contentType, fileName);
      
      const file = folder.createFile(blob);
      file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
      fileUrl = file.getUrl();
    }
    
    // 3. Сохраняем в Таблицу
    if (processedText || fileUrl) {
      const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getActiveSheet();
      const date = new Date();
      // Структура колонок: [Дата, Текст, Ссылка на файл]
      sheet.appendRow([date.toLocaleString('ru-RU'), processedText, fileUrl]);
    }
    
    return ContentService.createTextOutput(JSON.stringify({success: true, message: 'Успешно сохранено!'}))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({success: false, error: error.toString()}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function getLatestNotes() {
  try {
    const sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getActiveSheet();
    const data = sheet.getDataRange().getValues();
    
    if (data.length <= 1) return []; // Только заголовки
    
    let notes = [];
    for (let i = data.length - 1; i >= Math.max(1, data.length - 10); i--) {
      let row = data[i];
      if (!row[0] && !row[1]) continue;
      notes.push({
        date: row[0],
        text: row[1],
        fileUrl: row[2] || ''
      });
    }
    return notes;
  } catch (e) {
    return [{error: e.toString()}];
  }
}

function processWithGemini(text) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=${GEMINI_API_KEY}`;
  
  const prompt = `Ты помощник на производстве. Пользователь надиктовал свои мысли для сменных работников. Твоя задача: структурировать это в четкий, понятный "План / Заметки на смену". Убери воду, выдели главное пунктами.\n\nТекст пользователя:\n"${text}"`;

  const payload = {
    "contents": [{
      "parts": [{"text": prompt}]
    }]
  };
  
  const options = {
    'method': 'post',
    'contentType': 'application/json',
    'payload': JSON.stringify(payload),
    'muteHttpExceptions': true
  };
  
  try {
    const response = UrlFetchApp.fetch(url, options);
    const json = JSON.parse(response.getContentText());
    
    if (json.candidates && json.candidates.length > 0) {
      return json.candidates[0].content.parts[0].text;
    }
    return text;
  } catch (e) {
    return text + "\n(Ошибка Gemini: " + e.toString() + ")";
  }
}
