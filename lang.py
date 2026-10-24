# ─────────────────────────────────────────────────────────────
# Language selection for LUNC Assistant Bot.
# Per-USER preference (not per-group): one user switching language never
# changes what anyone else sees. Stored in store.py (user_lang table).
# The bot's AI answers (summaries, /ask, TL;DR, mentions, DM summaries)
# follow the requester's language. /start, /language and the picker are
# translated here. Data-command outputs (/price, /proposals, etc.) are
# mostly numbers + tickers and stay in English for now.
# Labels are in each language's own script so anyone can spot their
# language without reading English first.
# ─────────────────────────────────────────────────────────────

# (code, native label, English name used in the AI prompt)
LANGS = [
    ("en", "English", "English"),
    ("es", "Español", "Spanish"),
    ("pt", "Português", "Portuguese"),
    ("fr", "Français", "French"),
    ("de", "Deutsch", "German"),
    ("it", "Italiano", "Italian"),
    ("nl", "Nederlands", "Dutch"),
    ("ru", "Русский", "Russian"),
    ("uk", "Українська", "Ukrainian"),
    ("tr", "Türkçe", "Turkish"),
    ("ar", "العربية", "Arabic"),
    ("hi", "हिन्दी", "Hindi"),
    ("id", "Bahasa Indonesia", "Indonesian"),
    ("vi", "Tiếng Việt", "Vietnamese"),
    ("th", "ไทย", "Thai"),
    ("ko", "한국어", "Korean"),
    ("ja", "日本語", "Japanese"),
    ("zh", "简体中文", "Simplified Chinese"),
]

CODES = {c for c, _, _ in LANGS}
LABELS = {c: label for c, label, _ in LANGS}
ENGLISH_NAMES = {c: name for c, _, name in LANGS}
DEFAULT = "en"

# Short UI strings only. {name} = the language's native label.
# Russian/Ukrainian "picked" phrasing deliberately avoids case inflection
# ("all replies will be in this language") so the label slots in cleanly.
STRINGS = {
    "pick": {
        "en": "Choose your language:",
        "es": "Elige tu idioma:",
        "pt": "Escolha seu idioma:",
        "fr": "Choisissez votre langue :",
        "de": "Wähle deine Sprache:",
        "it": "Scegli la tua lingua:",
        "nl": "Kies je taal:",
        "ru": "Выберите язык:",
        "uk": "Оберіть мову:",
        "tr": "Dilinizi seçin:",
        "ar": "اختر لغتك:",
        "hi": "अपनी भाषा चुनें:",
        "id": "Pilih bahasa Anda:",
        "vi": "Chọn ngôn ngữ của bạn:",
        "th": "เลือกภาษาของคุณ:",
        "ko": "언어를 선택하세요:",
        "ja": "言語を選んでください:",
        "zh": "选择你的语言：",
    },
    "picked": {
        "en": "Language set to {name} — I'll reply in {name} from now on.",
        "es": "Idioma establecido: {name}. A partir de ahora responderé en {name}.",
        "pt": "Idioma definido: {name}. A partir de agora responderei em {name}.",
        "fr": "Langue définie : {name}. Je répondrai désormais en {name}.",
        "de": "Sprache eingestellt: {name}. Ich antworte ab jetzt auf {name}.",
        "it": "Lingua impostata: {name}. D'ora in poi risponderò in {name}.",
        "nl": "Taal ingesteld: {name}. Ik antwoord vanaf nu in {name}.",
        "ru": "Язык установлен: {name}. Все ответы будут на этом языке.",
        "uk": "Мову встановлено: {name}. Усі відповіді будуть цією мовою.",
        "tr": "Dil ayarlandı: {name}. Artık {name} yanıt vereceğim.",
        "ar": "تم تعيين اللغة: {name}. سأرد من الآن فصاعدًا بـ{name}.",
        "hi": "भाषा सेट हो गई: {name}। अब से मैं {name} में जवाब दूँगा।",
        "id": "Bahasa diatur: {name}. Mulai sekarang saya akan membalas dalam {name}.",
        "vi": "Đã đặt ngôn ngữ: {name}. Từ giờ tôi sẽ trả lời bằng {name}.",
        "th": "ตั้งค่าภาษาเป็น {name} แล้ว ต่อไปผมจะตอบเป็น {name}",
        "ko": "언어가 {name}(으)로 설정되었습니다. 이제부터 {name}(으)로 답변드리겠습니다.",
        "ja": "言語を{name}に設定しました。これからは{name}で返信します。",
        "zh": "语言已设置为 {name}，我从现在起会用 {name} 回复。",
    },
    "current": {
        "en": "Your language is {name}. Pick another below to change it.",
        "es": "Tu idioma es {name}. Elige otro abajo para cambiarlo.",
        "pt": "Seu idioma é {name}. Escolha outro abaixo para alterá-lo.",
        "fr": "Votre langue est {name}. Choisissez-en une autre ci-dessous pour la changer.",
        "de": "Deine Sprache ist {name}. Wähle unten eine andere, um sie zu ändern.",
        "it": "La tua lingua è {name}. Scegline un'altra qui sotto per cambiarla.",
        "nl": "Je taal is {name}. Kies hieronder een andere om te wijzigen.",
        "ru": "Ваш язык: {name}. Выберите другой ниже, чтобы изменить.",
        "uk": "Ваша мова: {name}. Оберіть іншу нижче, щоб змінити.",
        "tr": "Diliniz {name}. Değiştirmek için aşağıdan başka bir dil seçin.",
        "ar": "لغتك هي {name}. اختر لغة أخرى أدناه لتغييرها.",
        "hi": "आपकी भाषा {name} है। बदलने के लिए नीचे कोई और चुनें।",
        "id": "Bahasa Anda adalah {name}. Pilih yang lain di bawah untuk mengubahnya.",
        "vi": "Ngôn ngữ của bạn là {name}. Chọn ngôn ngữ khác bên dưới để thay đổi.",
        "th": "ภาษาของคุณคือ {name} เลือกภาษาอื่นด้านล่างเพื่อเปลี่ยน",
        "ko": "현재 언어는 {name}입니다. 변경하려면 아래에서 다른 언어를 선택하세요.",
        "ja": "現在の言語は{name}です。変更するには下から別の言語を選んでください。",
        "zh": "你当前的语言是 {name}。如需更改，请在下方选择其他语言。",
    },
    "intro": {
        "en": "🤖 I'm LUNC Assistant Bot — I summarize busy Telegram groups, answer Luna Classic questions, and show live prices, proposals, and staking help.\n\nTry /summary for a recap of the group, /ask to ask me anything, or pick your language below — I'll reply in the language you choose.",
        "es": "🤖 Soy LUNC Assistant Bot: resumo grupos de Telegram con muchos mensajes, respondo preguntas sobre Luna Classic y muestro precios en vivo, propuestas y ayuda sobre staking.\n\nPrueba /summary para un resumen del grupo, /ask para preguntarme cualquier cosa, o elige tu idioma abajo: responderé en el idioma que elijas.",
        "pt": "🤖 Sou o LUNC Assistant Bot: resumo grupos de Telegram com muitas mensagens, respondo perguntas sobre Luna Classic e mostro preços ao vivo, propostas e ajuda sobre staking.\n\nExperimente /summary para um resumo do grupo, /ask para me perguntar qualquer coisa, ou escolha seu idioma abaixo: responderei no idioma que você escolher.",
        "fr": "🤖 Je suis LUNC Assistant Bot : je résume les groupes Telegram très actifs, je réponds aux questions sur Luna Classic et j'affiche les prix en direct, les propositions et l'aide au staking.\n\nEssayez /summary pour un récapitulatif du groupe, /ask pour me poser une question, ou choisissez votre langue ci-dessous : je répondrai dans la langue choisie.",
        "de": "🤖 Ich bin der LUNC Assistant Bot: Ich fasse vielbeschäftigte Telegram-Gruppen zusammen, beantworte Fragen zu Luna Classic und zeige Live-Preise, Vorschläge und Staking-Hilfe.\n\nProbier /summary für eine Gruppenzusammenfassung, /ask um mich etwas zu fragen, oder wähle unten deine Sprache — ich antworte in der Sprache, die du wählst.",
        "it": "🤖 Sono LUNC Assistant Bot: riassumo i gruppi Telegram molto attivi, rispondo a domande su Luna Classic e mostro prezzi in tempo reale, proposte e aiuto sullo staking.\n\nProva /summary per un riepilogo del gruppo, /ask per chiedermi qualsiasi cosa, oppure scegli la tua lingua qui sotto: risponderò nella lingua che scegli.",
        "nl": "🤖 Ik ben LUNC Assistant Bot: ik vat drukke Telegram-groepen samen, beantwoord vragen over Luna Classic en toon live prijzen, voorstellen en staking-hulp.\n\nProbeer /summary voor een samenvatting van de groep, /ask om me iets te vragen, of kies hieronder je taal — ik antwoord in de taal die jij kiest.",
        "ru": "🤖 Я LUNC Assistant Bot: я делаю краткие обзоры активных групп Telegram, отвечаю на вопросы о Luna Classic и показываю цены в реальном времени, предложения и помощь по стейкингу.\n\nПопробуйте /summary для обзора группы, /ask чтобы задать мне вопрос, или выберите язык ниже — я буду отвечать на выбранном вами языке.",
        "uk": "🤖 Я LUNC Assistant Bot: роблю короткі огляди активних груп Telegram, відповідаю на запитання про Luna Classic та показую ціни в реальному часі, пропозиції і допомогу зі стейкінгом.\n\nСпробуйте /summary для огляду групи, /ask щоб поставити мені запитання, або оберіть мову нижче — я відповідатиму обраною вами мовою.",
        "tr": "🤖 Ben LUNC Assistant Bot: Yoğun Telegram gruplarını özetliyor, Luna Classic sorularını yanıtlıyor ve canlı fiyatları, teklifleri ve staking yardımını gösteriyorum.\n\nGrup özeti için /summary, bana soru sormak için /ask komutunu deneyin veya aşağıdan dilinizi seçin — seçtiğiniz dilde yanıt veririm.",
        "ar": "🤖 أنا LUNC Assistant Bot: ألخّص مجموعات تيليجرام النشطة، وأجيب عن أسئلة Luna Classic، وأعرض الأسعار المباشرة والمقترحات والمساعدة في الستاكينغ.\n\nجرّب /summary لملخص المجموعة، و/ask لطرح أي سؤال عليّ، أو اختر لغتك أدناه — سأرد باللغة التي تختارها.",
        "hi": "🤖 मैं LUNC Assistant Bot हूँ: मैं व्यस्त Telegram समूहों का सारांश बनाता हूँ, Luna Classic के सवालों का जवाब देता हूँ, और लाइव कीमतें, प्रस्ताव और स्टेकिंग मदद दिखाता हूँ।\n\nसमूह का सारांश पाने के लिए /summary, कुछ भी पूछने के लिए /ask आज़माएँ, या नीचे अपनी भाषा चुनें — मैं आपकी चुनी भाषा में जवाब दूँगा।",
        "id": "🤖 Saya LUNC Assistant Bot: saya merangkum grup Telegram yang ramai, menjawab pertanyaan tentang Luna Classic, dan menampilkan harga live, proposal, serta bantuan staking.\n\nCoba /summary untuk rekap grup, /ask untuk bertanya apa saja, atau pilih bahasa Anda di bawah — saya akan membalas dalam bahasa yang Anda pilih.",
        "vi": "🤖 Tôi là LUNC Assistant Bot: tôi tóm tắt các nhóm Telegram sôi động, trả lời câu hỏi về Luna Classic và hiển thị giá trực tiếp, đề xuất và trợ giúp staking.\n\nThử /summary để xem tóm tắt nhóm, /ask để hỏi tôi bất cứ điều gì, hoặc chọn ngôn ngữ của bạn bên dưới — tôi sẽ trả lời bằng ngôn ngữ bạn chọn.",
        "th": "🤖 ผมคือ LUNC Assistant Bot: ผมสรุปกลุ่ม Telegram ที่คึกคัก ตอบคำถามเกี่ยวกับ Luna Classic และแสดงราคาสด ข้อเสนอ และความช่วยเหลือเรื่อง staking\n\nลอง /summary เพื่อดูสรุปกลุ่ม /ask เพื่อถามอะไรก็ได้ หรือเลือกภาษาของคุณด้านล่าง — ผมจะตอบในภาษาที่คุณเลือก",
        "ko": "🤖 저는 LUNC Assistant Bot입니다. 활발한 텔레그램 그룹을 요약하고, Luna Classic에 대한 질문에 답하며, 실시간 가격, 제안, 스테이킹 도움을 보여줍니다.\n\n그룹 요약을 보려면 /summary, 무엇이든 물어보려면 /ask를 사용하거나 아래에서 언어를 선택하세요. 선택하신 언어로 답변드리겠습니다.",
        "ja": "🤖 私はLUNC Assistant Botです。活発なTelegramグループを要約し、Luna Classicに関する質問に答え、ライブ価格や提案、ステーキングのヘルプを表示します。\n\nグループの要約は /summary、質問は /ask を試すか、下で言語を選んでください。選んだ言語で返信します。",
        "zh": "🤖 我是 LUNC Assistant Bot：我会总结热闹的 Telegram 群组，回答 Luna Classic 相关问题，并显示实时价格、提案和质押帮助。\n\n试试 /summary 查看群组总结，用 /ask 向我提问，或在下方选择你的语言——我会用你选择的语言回复。",
    },
}


def normalize(code):
    """Any stored/unknown code falls back to English — never crash on it."""
    return code if code in CODES else DEFAULT


def t(key, lang=DEFAULT, **kw):
    """Translated UI string; falls back to English for a missing key/lang."""
    table = STRINGS.get(key, {})
    text = table.get(normalize(lang)) or table.get(DEFAULT, "")
    return text.format(**kw) if kw else text


def lang_keyboard():
    """Inline keyboard: 2 columns of native-script labels. Imported lazily
    so plain unit tests can use this module without python-telegram-bot."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for i in range(0, len(LANGS), 2):
        row = [InlineKeyboardButton(LANGS[j][1], callback_data=f"lang:{LANGS[j][0]}")
               for j in range(i, min(i + 2, len(LANGS)))]
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def instruction(lang):
    """Extra system-prompt line for AI replies. Empty for English."""
    lang = normalize(lang)
    if lang == DEFAULT:
        return ""
    return (f"Reply entirely in {ENGLISH_NAMES[lang]}. "
            "Keep tickers, contract addresses, wallet addresses, numbers, "
            "and command names exactly as-is — translate only the prose around them.")
