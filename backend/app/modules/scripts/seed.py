"""Initial call scripts, from the clinic's operator guide (RU + UZ).

"no_show" and "post_procedure" were not in the guide; they are drafts in the same style for the
clinic to review. Placeholders: [Ism] operator, [Bemor] patient, [sana], [vaqt], [shifokor],
[xizmat] (RU scripts use the same bracket names so the UI can fill them).
"""

SCRIPTS: list[dict[str, str | int]] = [
    # --- 1 ---
    {
        "code": "confirm",
        "language": "ru",
        "sort_order": 1,
        "title": "Утреннее подтверждение записи",
        "body": """Доброе утро! Вас беспокоит администратор Radeski Skin Clinic. Меня зовут [Ism].

Вам удобно сейчас разговаривать?

Вы записаны сегодня на [vaqt] к [shifokor] на [xizmat]. Хотела подтвердить, сможете ли вы прийти?

**Если пациент подтверждает:**
Отлично, спасибо за подтверждение! Мы будем ждать вас сегодня в [vaqt]. Пожалуйста, постарайтесь прийти немного заранее. До встречи в Radeski Skin Clinic!

**Если пациент не может прийти:**
Хорошо, понимаю. Давайте я предложу вам другое удобное время для записи.""",
    },
    {
        "code": "confirm",
        "language": "uz",
        "sort_order": 1,
        "title": "Ertalab yozuvni tasdiqlash",
        "body": """Assalomu alaykum! Xayrli tong!
Siz bilan Radeski Skin Clinic klinikasi operatori bog'lanmoqda. Mening ismim [Ism].

Hozir gaplashishga qulaymi?

Siz bugun soat [vaqt] da [shifokor] qabuliga [xizmat] uchun yozilgansiz. Kelishingizni tasdiqlamoqchi edik. Kela olasizmi?

**Agar bemor tasdiqlasa:**
Ajoyib, tasdiqlaganingiz uchun rahmat! Sizni bugun soat [vaqt] da kutib qolamiz. Iltimos, belgilangan vaqtdan biroz oldinroq kelishga harakat qiling. Radeski Skin Clinic'da ko'rishguncha!

**Agar bemor kela olmasa:**
Tushunarli. Unda siz uchun boshqa qulay vaqtni tanlab beraman.""",
    },
    # --- 2 ---
    {
        "code": "incoming",
        "language": "ru",
        "sort_order": 2,
        "title": "Входящий звонок",
        "body": """Здравствуйте! Radeski Skin Clinic, меня зовут [Ism]. Чем я могу вам помочь?

**Если пациент хочет записаться:**
Конечно, с удовольствием помогу вам подобрать удобное время. Подскажите, пожалуйста, как я могу к вам обращаться? Какая проблема или процедура вас интересует?

**После ответа:**
По вашему вопросу рекомендована консультация [shifokor]. Могу предложить вам следующие варианты: [1-vaqt] или [2-vaqt]. Какой вариант вам удобнее?

**После записи:**
Отлично, я записала вас на [sana] в [vaqt]. Мы также отправим вам подтверждение. Спасибо за обращение в Radeski Skin Clinic! Будем ждать вас.""",
    },
    {
        "code": "incoming",
        "language": "uz",
        "sort_order": 2,
        "title": "Kiruvchi qo'ng'iroq",
        "body": """Assalomu alaykum! Radeski Skin Clinic, mening ismim [Ism]. Sizga qanday yordam bera olaman?

**Agar bemor yozilmoqchi bo'lsa:**
Albatta, siz uchun qulay vaqtni tanlashga yordam beraman. Iltimos, sizga qanday murojaat qilishim mumkin? Sizni qanday muammo yoki qaysi muolaja qiziqtiryapti?

**Javobdan so'ng:**
Sizning murojaatingiz bo'yicha [shifokor] konsultatsiyasi tavsiya etiladi. Sizga quyidagi vaqtlarni taklif qila olaman: [1-vaqt] yoki [2-vaqt]. Qaysi biri sizga qulay?

**Yozuv tasdiqlangandan so'ng:**
Ajoyib, sizni [sana] kuni soat [vaqt] ga yozib qo'ydim. Sizga tasdiqlovchi xabar ham yuboriladi. Radeski Skin Clinic'ga murojaat qilganingiz uchun rahmat! Sizni kutib qolamiz.""",
    },
    # --- 3 ---
    {
        "code": "repeat_visit",
        "language": "ru",
        "sort_order": 3,
        "title": "Повторная консультация",
        "body": """Здравствуйте, [Bemor]! Вас беспокоит Radeski Skin Clinic, меня зовут [Ism].

Вы недавно были на консультации у [shifokor]. Мы связываемся с вами, чтобы записать вас на повторный осмотр и оценить результаты лечения. Вам будет удобно прийти на повторную консультацию?

**Если пациент согласен:**
Отлично. Могу предложить вам [1-vaqt] или [2-vaqt]. Как вам будет удобнее?

**После записи:**
Спасибо! Я записала вас. Будем ждать вас [sana] в [vaqt]. Желаем вам хорошего дня!""",
    },
    {
        "code": "repeat_visit",
        "language": "uz",
        "sort_order": 3,
        "title": "Qayta konsultatsiyaga yozish",
        "body": """Assalomu alaykum, [Bemor]!
Siz bilan Radeski Skin Clinic klinikasi operatori, mening ismim [Ism].

Siz yaqinda [shifokor] qabulida bo'lgansiz. Sizni qayta ko'rikdan o'tkazish va davolash natijalarini baholash uchun bog'lanmoqdamiz. Qayta konsultatsiyaga kelishingizga qulay bo'ladimi?

**Agar bemor rozi bo'lsa:**
Ajoyib. Sizga [1-vaqt] yoki [2-vaqt] ni taklif qila olaman. Qaysi biri sizga qulay?

**Yozib bo'lgandan so'ng:**
Rahmat! Sizni yozib qo'ydim. Sizni [sana] kuni soat [vaqt] da kutib qolamiz. Sizga yaxshi kun tilaymiz!""",
    },
    # --- 4 ---
    {
        "code": "procedure",
        "language": "ru",
        "sort_order": 4,
        "title": "Запись на процедуру",
        "body": """Здравствуйте! Radeski Skin Clinic, меня зовут [Ism]. Вы хотели записаться на процедуру [xizmat], верно?

Подскажите, пожалуйста, вы уже проходили консультацию у нашего специалиста?

**Если консультация была:**
Отлично. Давайте подберём для вас удобное время.

**Если консультации не было:**
В некоторых случаях перед процедурой необходима консультация специалиста, чтобы врач оценил состояние кожи/волос и подобрал наиболее подходящую процедуру. Я могу записать вас на консультацию.""",
    },
    {
        "code": "procedure",
        "language": "uz",
        "sort_order": 4,
        "title": "Muolajaga yozish",
        "body": """Assalomu alaykum! Radeski Skin Clinic, mening ismim [Ism]. Siz [xizmat] ga yozilmoqchi edingiz, to'g'rimi?

Iltimos, ayting, siz avval bizning mutaxassisimiz konsultatsiyasida bo'lgansizmi?

**Agar konsultatsiyada bo'lgan bo'lsa:**
Juda yaxshi. Unda siz uchun qulay vaqtni tanlab beraman.

**Agar konsultatsiyada bo'lmagan bo'lsa:**
Ba'zi muolajalardan oldin mutaxassis konsultatsiyasi talab qilinadi. Shifokor teri yoki soch holatini baholab, sizga eng mos muolajani tavsiya qiladi. Sizni konsultatsiyaga yozib qo'yishim mumkin.""",
    },
    # --- 5 ---
    {
        "code": "laser",
        "language": "ru",
        "sort_order": 5,
        "title": "Лазерная эпиляция",
        "body": """Здравствуйте! Radeski Skin Clinic, меня зовут [Ism]. Чем могу помочь?

**Если пациент интересуется эпиляцией:**
Конечно! У нас проводится лазерная эпиляция. Подскажите, пожалуйста, какую зону вы хотели бы обработать?

**После уточнения:**
Я могу подобрать для вас ближайшее удобное время. Вам удобнее прийти утром, днём или вечером?

**После записи:**
Отлично, я записала вас на [sana] в [vaqt]. Перед процедурой мы дополнительно расскажем вам о необходимой подготовке. Спасибо за обращение! Будем ждать вас в Radeski Skin Clinic.""",
    },
    {
        "code": "laser",
        "language": "uz",
        "sort_order": 5,
        "title": "Lazer epilyatsiyasi",
        "body": """Assalomu alaykum! Radeski Skin Clinic, mening ismim [Ism]. Sizga qanday yordam bera olaman?

**Agar bemor lazer epilyatsiyasi bilan qiziqsa:**
Albatta! Klinikamizda lazer epilyatsiyasi xizmati mavjud. Iltimos, qaysi sohada lazer epilyatsiyasini qilmoqchi ekanligingizni ayting?

**Keyin:**
Siz uchun eng yaqin qulay vaqtni tanlab beraman. Sizga ertalab, kunduzi yoki kechqurun kelish qulaymi?

**Yozib bo'lgandan so'ng:**
Ajoyib, sizni [sana] kuni soat [vaqt] ga yozib qo'ydim. Muolajadan oldin sizga kerakli tayyorgarlik bo'yicha ma'lumot beriladi. Murojaatingiz uchun rahmat! Sizni Radeski Skin Clinic'da kutib qolamiz.""",
    },
    # --- 6 ---
    {
        "code": "reactivation",
        "language": "ru",
        "sort_order": 6,
        "title": "Обзвон базы и приглашение",
        "body": """_Важно: не звучать навязчиво._

Здравствуйте, [Bemor]! Вас беспокоит Radeski Skin Clinic, меня зовут [Ism].

Ранее вы обращались в нашу клинику, поэтому мы решили связаться с вами и узнать, как вы себя чувствуете и всё ли хорошо.

Сейчас у нас ведут приём специалисты по дерматологии / трихологии, также доступны современные диагностические и лечебные процедуры. Если у вас есть вопросы по состоянию кожи или волос, мы можем подобрать для вас удобное время для консультации.

**Если пациент заинтересован:**
С удовольствием подберу для вас удобное время. Вам удобнее [1-vaqt] или [2-vaqt]?

**Если пациент не заинтересован:**
Хорошо, спасибо за ответ! Если вам понадобится консультация, мы всегда будем рады вам помочь. Хорошего дня!""",
    },
    {
        "code": "reactivation",
        "language": "uz",
        "sort_order": 6,
        "title": "Bazaga qo'ng'iroq va taklif",
        "body": """_Muhim: bemorga majburlovchi yoki bezovta qiluvchi tarzda gapirmaslik kerak._

Assalomu alaykum, [Bemor]! Siz bilan Radeski Skin Clinic klinikasi operatori bog'lanmoqda. Mening ismim [Ism].

Siz avval klinikamizga murojaat qilgansiz. Shu sababli siz bilan bog'lanib, holatingiz qandayligini va hammasi yaxshi ekanligini bilmoqchi edik.

Hozirda klinikamizda dermatologiya va trixologiya yo'nalishlarida mutaxassislar qabul qilmoqda, shuningdek, zamonaviy diagnostika va muolajalar mavjud. Agar sizda teri yoki soch holati bo'yicha savollar bo'lsa, siz uchun konsultatsiyaga qulay vaqt tanlab berishimiz mumkin.

**Agar bemor qiziqsa:**
Albatta, siz uchun qulay vaqtni tanlab beraman. Sizga [1-vaqt] yoki [2-vaqt] qulay bo'ladimi?

**Agar bemor qiziqmasa:**
Tushunarli, javobingiz uchun rahmat! Agar sizga konsultatsiya kerak bo'lsa, biz har doim yordam berishga tayyormiz. Sizga yaxshi kun tilaymiz!""",
    },
    # --- 7 ---
    {
        "code": "thinking",
        "language": "ru",
        "sort_order": 7,
        "title": "«Я подумаю»",
        "body": """Конечно, я понимаю.

Если хотите, я могу пока предложить вам удобные варианты записи, а вы выберете подходящее время.

**Или:**
Хорошо. Если у вас появятся вопросы или вы решите записаться, пожалуйста, обращайтесь. Мы с удовольствием вам поможем.

_Важно: не давить на пациента._""",
    },
    {
        "code": "thinking",
        "language": "uz",
        "sort_order": 7,
        "title": "«O'ylab ko'raman»",
        "body": """Albatta, tushunaman.

Agar xohlasangiz, sizga qulay bo'lishi mumkin bo'lgan vaqtlarni taklif qilaman, siz o'zingizga mos vaqtni tanlaysiz.

**Yoki:**
Yaxshi. Agar sizda savollar paydo bo'lsa yoki yozilishga qaror qilsangiz, bemalol bizga murojaat qiling. Sizga mamnuniyat bilan yordam beramiz.

_Muhim: bemorga bosim o'tkazmaslik kerak._""",
    },
    # --- 8 ---
    {
        "code": "price",
        "language": "ru",
        "sort_order": 8,
        "title": "Вопрос о цене",
        "body": """Стоимость зависит от [zona / muolaja / hajm]. Я могу подробно сориентировать вас по стоимости.

**Если нужна консультация врача:**
Точную программу лечения и необходимое количество процедур врач сможет определить после осмотра. Я могу записать вас на консультацию к специалисту.""",
    },
    {
        "code": "price",
        "language": "uz",
        "sort_order": 8,
        "title": "Narx haqida savol",
        "body": """Muolajaning narxi [zona / muolaja / hajm] ga qarab belgilanadi. Men sizni narxlar bo'yicha batafsil ma'lumot bilan tanishtira olaman.

**Agar shifokor konsultatsiyasi kerak bo'lsa:**
Davolash dasturi va kerakli muolajalar sonini shifokor ko'rikdan so'ng aniq belgilaydi. Sizni mutaxassis konsultatsiyasiga yozib qo'yishim mumkin.""",
    },
    # --- 9 ---
    {
        "code": "medical",
        "language": "ru",
        "sort_order": 9,
        "title": "Медицинский вопрос",
        "body": """_Оператор не ставит диагноз и не назначает лечение._

Понимаю ваше беспокойство. Чтобы специалист мог определить причину и подобрать правильное лечение, необходима консультация.

Я могу записать вас к нашему специалисту. Когда вам будет удобнее прийти?""",
    },
    {
        "code": "medical",
        "language": "uz",
        "sort_order": 9,
        "title": "Tibbiy savol",
        "body": """_Operator tashxis qo'ymasligi va davolash tavsiya qilmasligi kerak._

Tushunaman, bu sizni xavotirga solayotgan bo'lishi mumkin. Sababini aniqlash va to'g'ri davolashni tanlash uchun mutaxassis konsultatsiyasi zarur.

Sizni mutaxassis qabuliga yozib qo'yishim mumkin. Qaysi kun sizga qulay?""",
    },
    # --- 10 ---
    {
        "code": "complaint",
        "language": "ru",
        "sort_order": 10,
        "title": "Недовольство или жалоба",
        "body": """Я вас услышала и понимаю ваше беспокойство. Чтобы мы могли разобраться в ситуации, пожалуйста, уточните подробнее, что произошло.

**После получения информации:**
Спасибо, что подробно объяснили ситуацию. Я обязательно передам информацию ответственному специалисту/руководителю. Мы свяжемся с вами после уточнения всех деталей.

**Оператору нельзя:** спорить; оправдываться; обвинять пациента; обещать то, чего клиника не может гарантировать.""",
    },
    {
        "code": "complaint",
        "language": "uz",
        "sort_order": 10,
        "title": "Norozilik yoki shikoyat",
        "body": """Men sizni tushundim va xavotiringizni inobatga olaman. Vaziyatni yaxshiroq tushunishimiz uchun, iltimos, nima bo'lganini batafsilroq aytib bera olasizmi?

**Ma'lumotni eshitgandan so'ng:**
Vaziyatni batafsil tushuntirib berganingiz uchun rahmat. Men bu ma'lumotni albatta mas'ul mutaxassis yoki rahbariyatga yetkazaman. Barcha tafsilotlarni aniqlaganimizdan so'ng, siz bilan bog'lanamiz.

**Operatorga mumkin emas:** bemor bilan tortishish; o'zini oqlash; bemorni ayblash; klinika kafolat bermaydigan narsalarni va'da qilish.""",
    },
    # --- 11 ---
    {
        "code": "no_answer",
        "language": "ru",
        "sort_order": 11,
        "title": "Пациент не отвечает",
        "body": """После первого пропущенного звонка — сделать повторный звонок позже.

**Сообщение, если пациент не отвечает:**
Добрый день! Вас беспокоит Radeski Skin Clinic. Мы пытались связаться с вами по поводу вашей записи. Пожалуйста, перезвоните нам или ответьте на сообщение.""",
    },
    {
        "code": "no_answer",
        "language": "uz",
        "sort_order": 11,
        "title": "Bemor javob bermasa",
        "body": """Birinchi qo'ng'iroqdan keyin ma'lum vaqtdan so'ng yana qo'ng'iroq qilish mumkin.

**Bemor javob bermasa yuboriladigan xabar:**
Assalomu alaykum! Siz bilan Radeski Skin Clinic bog'lanishga harakat qildi. Qo'ng'irog'imiz sizning yozuvingiz bilan bog'liq edi. Iltimos, bizga qayta qo'ng'iroq qiling yoki xabarimizga javob bering.""",
    },
    # --- 12 ---
    {
        "code": "closing",
        "language": "ru",
        "sort_order": 12,
        "title": "Завершение разговора",
        "body": """Спасибо за обращение в Radeski Skin Clinic! Если у вас появятся дополнительные вопросы, вы всегда можете связаться с нами. Хорошего вам дня! До свидания!""",
    },
    {
        "code": "closing",
        "language": "uz",
        "sort_order": 12,
        "title": "Suhbatni yakunlash",
        "body": """Radeski Skin Clinic'ga murojaat qilganingiz uchun rahmat! Agar sizda qo'shimcha savollar bo'lsa, istalgan vaqtda biz bilan bog'lanishingiz mumkin. Sizga yaxshi kun tilaymiz! Xayr, salomat bo'ling!""",
    },
    # --- drafts (not in the guide) ---
    {
        "code": "no_show",
        "language": "ru",
        "sort_order": 13,
        "title": "Пациент не пришёл (черновик)",
        "body": """Здравствуйте, [Bemor]! Вас беспокоит Radeski Skin Clinic, меня зовут [Ism].

Сегодня вы были записаны на [vaqt] к [shifokor], но, к сожалению, мы вас не дождались. Всё ли у вас в порядке?

**Выяснить причину (без упрёков) и предложить:**
Давайте я подберу вам другое удобное время. Могу предложить [1-vaqt] или [2-vaqt].""",
    },
    {
        "code": "no_show",
        "language": "uz",
        "sort_order": 13,
        "title": "Bemor kelmadi (qoralama)",
        "body": """Assalomu alaykum, [Bemor]! Siz bilan Radeski Skin Clinic operatori [Ism] bog'lanmoqda.

Bugun soat [vaqt] da [shifokor] qabuliga yozilgan edingiz, afsuski sizni kuta olmadik. Hammasi joyidami?

**Sababini (ayblamasdan) aniqlab, taklif qiling:**
Siz uchun boshqa qulay vaqtni tanlab beraman. [1-vaqt] yoki [2-vaqt] ni taklif qila olaman.""",
    },
    {
        "code": "post_procedure",
        "language": "ru",
        "sort_order": 14,
        "title": "Звонок после процедуры (черновик)",
        "body": """Здравствуйте, [Bemor]! Вас беспокоит Radeski Skin Clinic, меня зовут [Ism].

Вы недавно были у нас на процедуре [xizmat]. Хотели узнать, как вы себя чувствуете, всё ли в порядке?

**Если есть жалобы:** не давать медицинских советов — передать информацию врачу и пообещать обратный звонок.
**Если всё хорошо:** напомнить о следующем визите или рекомендованной процедуре.""",
    },
    {
        "code": "post_procedure",
        "language": "uz",
        "sort_order": 14,
        "title": "Muolajadan keyingi qo'ng'iroq (qoralama)",
        "body": """Assalomu alaykum, [Bemor]! Siz bilan Radeski Skin Clinic operatori [Ism] bog'lanmoqda.

Siz yaqinda bizda [xizmat] muolajasida bo'lgansiz. O'zingizni qanday his qilyapsiz, hammasi joyidami?

**Shikoyat bo'lsa:** tibbiy maslahat bermang — ma'lumotni shifokorga yetkazing va qayta qo'ng'iroq qilishni va'da qiling.
**Hammasi yaxshi bo'lsa:** keyingi tashrif yoki tavsiya etilgan muolaja haqida eslating.""",
    },
]
