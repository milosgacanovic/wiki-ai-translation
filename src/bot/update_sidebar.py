from __future__ import annotations

import argparse
import logging

from .config import load_config
from .logging import configure_logging
from .mediawiki import MediaWikiClient

log = logging.getLogger("bot.update_sidebar")


SIDEBAR_BY_LANG: dict[str, str] = {
    "he": """* navigation
** Welcome_to_the_DanceResource_Wiki/he|ברוכים הבאים ל-DanceResource Wiki
** Introduction_to_Conscious_Dance/he|מבוא למחול מודע
** Core_Methods_and_Techniques/he|שיטות וטכניקות יסוד
** Curated_Resource_Library/he|ספריית משאבים נבחרים
** Benefits_of_Conscious_Dance/he|יתרונות המחול המודע
** Scientific_Research_and_Evidence/he|מחקר מדעי וראיות
** Historical_and_Cultural_Context/he|הקשר היסטורי ותרבותי
** Conscious_Dance_Practices/he|פרקטיקות מבוססות של מחול מודע
** Community_and_Global_Collaboration/he|קהילה ושיתוף פעולה גלובלי
** Future_Directions_and_Vision/he|כיוונים עתידיים וחזון
** Appendices/he|נספחים
** recentchanges-url|recentchanges
** Join_Our_Community/he|הצטרפו לקהילה
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "da": """* navigation
** Welcome_to_the_DanceResource_Wiki/da|Velkommen til DanceResource Wiki
** Introduction_to_Conscious_Dance/da|Introduktion til bevidst dans
** Core_Methods_and_Techniques/da|Grundlæggende metoder og teknikker
** Curated_Resource_Library/da|Kurateret ressourcebibliotek
** Benefits_of_Conscious_Dance/da|Fordele ved bevidst dans
** Scientific_Research_and_Evidence/da|Videnskabelig forskning og evidens
** Historical_and_Cultural_Context/da|Historisk og kulturel kontekst
** Conscious_Dance_Practices/da|Etablerede praksisser for bevidst dans
** Community_and_Global_Collaboration/da|Fællesskab og globalt samarbejde
** Future_Directions_and_Vision/da|Fremtidige retninger og vision
** Appendices/da|Bilag
** recentchanges-url|recentchanges
** Join_Our_Community/da|Bliv en del af fællesskabet
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "pt": """* navigation
** Welcome_to_the_DanceResource_Wiki/pt|Bem-vindos à DanceResource Wiki
** Introduction_to_Conscious_Dance/pt|Introdução à dança consciente
** Core_Methods_and_Techniques/pt|Métodos e técnicas fundamentais
** Curated_Resource_Library/pt|Biblioteca de recursos curados
** Benefits_of_Conscious_Dance/pt|Benefícios da dança consciente
** Scientific_Research_and_Evidence/pt|Pesquisa científica e evidências
** Historical_and_Cultural_Context/pt|Contexto histórico e cultural
** Conscious_Dance_Practices/pt|Práticas estabelecidas de dança consciente
** Community_and_Global_Collaboration/pt|Comunidade e colaboração global
** Future_Directions_and_Vision/pt|Direções futuras e visão
** Appendices/pt|Apêndices
** recentchanges-url|recentchanges
** Join_Our_Community/pt|Junte-se à comunidade
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "pl": """* navigation
** Welcome_to_the_DanceResource_Wiki/pl|Witamy w DanceResource Wiki
** Introduction_to_Conscious_Dance/pl|Wprowadzenie do tańca świadomego
** Core_Methods_and_Techniques/pl|Podstawowe metody i techniki
** Curated_Resource_Library/pl|Biblioteka wyselekcjonowanych zasobów
** Benefits_of_Conscious_Dance/pl|Korzyści tańca świadomego
** Scientific_Research_and_Evidence/pl|Badania naukowe i dowody
** Historical_and_Cultural_Context/pl|Kontekst historyczny i kulturowy
** Conscious_Dance_Practices/pl|Ugruntowane praktyki tańca świadomego
** Community_and_Global_Collaboration/pl|Społeczność i globalna współpraca
** Future_Directions_and_Vision/pl|Przyszłe kierunki i wizja
** Appendices/pl|Aneksy
** recentchanges-url|recentchanges
** Join_Our_Community/pl|Dołącz do społeczności
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "el": """* navigation
** Welcome_to_the_DanceResource_Wiki/el|Καλώς ήρθατε στο DanceResource Wiki
** Introduction_to_Conscious_Dance/el|Εισαγωγή στον συνειδητό χορό
** Core_Methods_and_Techniques/el|Βασικές μέθοδοι και τεχνικές
** Curated_Resource_Library/el|Επιμελημένη βιβλιοθήκη πόρων
** Benefits_of_Conscious_Dance/el|Οφέλη του συνειδητού χορού
** Scientific_Research_and_Evidence/el|Επιστημονική έρευνα και τεκμήρια
** Historical_and_Cultural_Context/el|Ιστορικό και πολιτισμικό πλαίσιο
** Conscious_Dance_Practices/el|Καθιερωμένες πρακτικές συνειδητού χορού
** Community_and_Global_Collaboration/el|Κοινότητα και παγκόσμια συνεργασία
** Future_Directions_and_Vision/el|Μελλοντικές κατευθύνσεις και όραμα
** Appendices/el|Παραρτήματα
** recentchanges-url|recentchanges
** Join_Our_Community/el|Γίνετε μέλος της κοινότητας
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "hu": """* navigation
** Welcome_to_the_DanceResource_Wiki/hu|Üdvözöljük a DanceResource Wiki oldalon
** Introduction_to_Conscious_Dance/hu|Bevezetés a tudatos táncba
** Core_Methods_and_Techniques/hu|Alapvető módszerek és technikák
** Curated_Resource_Library/hu|Válogatott erőforrások könyvtára
** Benefits_of_Conscious_Dance/hu|A tudatos tánc előnyei
** Scientific_Research_and_Evidence/hu|Tudományos kutatás és bizonyítékok
** Historical_and_Cultural_Context/hu|Történelmi és kulturális kontextus
** Conscious_Dance_Practices/hu|Bevált tudatos tánc gyakorlatok
** Community_and_Global_Collaboration/hu|Közösség és globális együttműködés
** Future_Directions_and_Vision/hu|Jövőbeli irányok és vízió
** Appendices/hu|Függelékek
** recentchanges-url|recentchanges
** Join_Our_Community/hu|Csatlakozz a közösséghez
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "sv": """* navigation
** Welcome_to_the_DanceResource_Wiki/sv|Välkommen till DanceResource Wiki
** Introduction_to_Conscious_Dance/sv|Introduktion till medveten dans
** Core_Methods_and_Techniques/sv|Grundläggande metoder och tekniker
** Curated_Resource_Library/sv|Kurerat resursbibliotek
** Benefits_of_Conscious_Dance/sv|Fördelar med medveten dans
** Scientific_Research_and_Evidence/sv|Vetenskaplig forskning och evidens
** Historical_and_Cultural_Context/sv|Historisk och kulturell kontext
** Conscious_Dance_Practices/sv|Etablerade praktiker för medveten dans
** Community_and_Global_Collaboration/sv|Gemenskap och globalt samarbete
** Future_Directions_and_Vision/sv|Framtida riktningar och vision
** Appendices/sv|Bilagor
** recentchanges-url|recentchanges
** Join_Our_Community/sv|Gå med i gemenskapen
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "fi": """* navigation
** Welcome_to_the_DanceResource_Wiki/fi|Tervetuloa DanceResource Wikiin
** Introduction_to_Conscious_Dance/fi|Johdanto tietoiseen tanssiin
** Core_Methods_and_Techniques/fi|Keskeiset menetelmät ja tekniikat
** Curated_Resource_Library/fi|Kuratoitu resurssikirjasto
** Benefits_of_Conscious_Dance/fi|Tietoisen tanssin hyödyt
** Scientific_Research_and_Evidence/fi|Tieteellinen tutkimus ja näyttö
** Historical_and_Cultural_Context/fi|Historiallinen ja kulttuurinen konteksti
** Conscious_Dance_Practices/fi|Vakiintuneet tietoisen tanssin käytännöt
** Community_and_Global_Collaboration/fi|Yhteisö ja globaali yhteistyö
** Future_Directions_and_Vision/fi|Tulevat suuntaukset ja visio
** Appendices/fi|Liitteet
** recentchanges-url|recentchanges
** Join_Our_Community/fi|Liity yhteisöön
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "sk": """* navigation
** Welcome_to_the_DanceResource_Wiki/sk|Vitajte v DanceResource Wiki
** Introduction_to_Conscious_Dance/sk|Úvod do vedomého tanca
** Core_Methods_and_Techniques/sk|Základné metódy a techniky
** Curated_Resource_Library/sk|Knižnica vybraných zdrojov
** Benefits_of_Conscious_Dance/sk|Prínosy vedomého tanca
** Scientific_Research_and_Evidence/sk|Vedecký výskum a dôkazy
** Historical_and_Cultural_Context/sk|Historický a kultúrny kontext
** Conscious_Dance_Practices/sk|Zavedené praktiky vedomého tanca
** Community_and_Global_Collaboration/sk|Komunita a globálna spolupráca
** Future_Directions_and_Vision/sk|Budúce smerovania a vízia
** Appendices/sk|Prílohy
** recentchanges-url|recentchanges
** Join_Our_Community/sk|Pridajte sa ku komunite
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "hr": """* navigation
** Welcome_to_the_DanceResource_Wiki/hr|Dobrodošli na DanceResource Wiki
** Introduction_to_Conscious_Dance/hr|Uvod u svjesni ples
** Core_Methods_and_Techniques/hr|Osnovne metode i tehnike
** Curated_Resource_Library/hr|Biblioteka odabranih resursa
** Benefits_of_Conscious_Dance/hr|Prednosti svjesnog plesa
** Scientific_Research_and_Evidence/hr|Znanstvena istraživanja i dokazi
** Historical_and_Cultural_Context/hr|Povijesni i kulturni kontekst
** Conscious_Dance_Practices/hr|Utemeljene prakse svjesnog plesa
** Community_and_Global_Collaboration/hr|Zajednica i globalna suradnja
** Future_Directions_and_Vision/hr|Budući smjerovi i vizija
** Appendices/hr|Dodaci
** recentchanges-url|recentchanges
** Join_Our_Community/hr|Pridružite se zajednici
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "id": """* navigation
** Welcome_to_the_DanceResource_Wiki/id|Selamat datang di DanceResource Wiki
** Introduction_to_Conscious_Dance/id|Pengantar tari sadar
** Core_Methods_and_Techniques/id|Metode dan teknik inti
** Curated_Resource_Library/id|Perpustakaan sumber daya terkurasi
** Benefits_of_Conscious_Dance/id|Manfaat tari sadar
** Scientific_Research_and_Evidence/id|Riset ilmiah dan bukti
** Historical_and_Cultural_Context/id|Konteks sejarah dan budaya
** Conscious_Dance_Practices/id|Praktik tari sadar yang mapan
** Community_and_Global_Collaboration/id|Komunitas dan kolaborasi global
** Future_Directions_and_Vision/id|Arah masa depan dan visi
** Appendices/id|Lampiran
** recentchanges-url|recentchanges
** Join_Our_Community/id|Bergabung dengan komunitas
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "ar": """* navigation
** Welcome_to_the_DanceResource_Wiki/ar|مرحبًا بكم في DanceResource Wiki
** Introduction_to_Conscious_Dance/ar|مقدمة في الرقص الواعي
** Core_Methods_and_Techniques/ar|الأساليب والتقنيات الأساسية
** Curated_Resource_Library/ar|مكتبة الموارد المختارة
** Benefits_of_Conscious_Dance/ar|فوائد الرقص الواعي
** Scientific_Research_and_Evidence/ar|البحث العلمي والأدلة
** Historical_and_Cultural_Context/ar|السياق التاريخي والثقافي
** Conscious_Dance_Practices/ar|ممارسات الرقص الواعي المعتمدة
** Community_and_Global_Collaboration/ar|المجتمع والتعاون العالمي
** Future_Directions_and_Vision/ar|التوجهات المستقبلية والرؤية
** Appendices/ar|الملاحق
** recentchanges-url|recentchanges
** Join_Our_Community/ar|انضم إلى المجتمع
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "hi": """* navigation
** Welcome_to_the_DanceResource_Wiki/hi|DanceResource Wiki में आपका स्वागत है
** Introduction_to_Conscious_Dance/hi|सचेत नृत्य का परिचय
** Core_Methods_and_Techniques/hi|मूल विधियाँ और तकनीकें
** Curated_Resource_Library/hi|चयनित संसाधन पुस्तकालय
** Benefits_of_Conscious_Dance/hi|सचेत नृत्य के लाभ
** Scientific_Research_and_Evidence/hi|वैज्ञानिक अनुसंधान और प्रमाण
** Historical_and_Cultural_Context/hi|ऐतिहासिक और सांस्कृतिक संदर्भ
** Conscious_Dance_Practices/hi|स्थापित सचेत नृत्य अभ्यास
** Community_and_Global_Collaboration/hi|समुदाय और वैश्विक सहयोग
** Future_Directions_and_Vision/hi|भविष्य की दिशाएँ और दृष्टि
** Appendices/hi|परिशिष्ट
** recentchanges-url|recentchanges
** Join_Our_Community/hi|समुदाय से जुड़ें
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "no": """* navigation
** Welcome_to_the_DanceResource_Wiki/no|Velkommen til DanceResource Wiki
** Introduction_to_Conscious_Dance/no|Introduksjon til bevisst dans
** Core_Methods_and_Techniques/no|Grunnleggende metoder og teknikker
** Curated_Resource_Library/no|Kurert ressursbibliotek
** Benefits_of_Conscious_Dance/no|Fordeler med bevisst dans
** Scientific_Research_and_Evidence/no|Vitenskapelig forskning og evidens
** Historical_and_Cultural_Context/no|Historisk og kulturell kontekst
** Conscious_Dance_Practices/no|Etablerte praksiser for bevisst dans
** Community_and_Global_Collaboration/no|Fellesskap og globalt samarbeid
** Future_Directions_and_Vision/no|Fremtidige retninger og visjon
** Appendices/no|Vedlegg
** recentchanges-url|recentchanges
** Join_Our_Community/no|Bli med i fellesskapet
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "cs": """* navigation
** Welcome_to_the_DanceResource_Wiki/cs|Vítejte na DanceResource Wiki
** Introduction_to_Conscious_Dance/cs|Úvod do vědomého tance
** Core_Methods_and_Techniques/cs|Základní metody a techniky
** Curated_Resource_Library/cs|Knihovna vybraných zdrojů
** Benefits_of_Conscious_Dance/cs|Přínosy vědomého tance
** Scientific_Research_and_Evidence/cs|Vědecký výzkum a důkazy
** Historical_and_Cultural_Context/cs|Historický a kulturní kontext
** Conscious_Dance_Practices/cs|Zavedené praktiky vědomého tance
** Community_and_Global_Collaboration/cs|Komunita a globální spolupráce
** Future_Directions_and_Vision/cs|Budoucí směry a vize
** Appendices/cs|Přílohy
** recentchanges-url|recentchanges
** Join_Our_Community/cs|Připojte se ke komunitě
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "ko": """* navigation
** Welcome_to_the_DanceResource_Wiki/ko|DanceResource Wiki에 오신 것을 환영합니다
** Introduction_to_Conscious_Dance/ko|의식적인 춤 소개
** Core_Methods_and_Techniques/ko|핵심 방법과 기술
** Curated_Resource_Library/ko|큐레이션된 자료 라이브러리
** Benefits_of_Conscious_Dance/ko|의식적인 춤의 이점
** Scientific_Research_and_Evidence/ko|과학적 연구와 근거
** Historical_and_Cultural_Context/ko|역사적·문화적 맥락
** Conscious_Dance_Practices/ko|확립된 의식적 춤 실천
** Community_and_Global_Collaboration/ko|커뮤니티와 글로벌 협력
** Future_Directions_and_Vision/ko|미래 방향과 비전
** Appendices/ko|부록
** recentchanges-url|recentchanges
** Join_Our_Community/ko|커뮤니티에 참여하기
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "ja": """* navigation
** Welcome_to_the_DanceResource_Wiki/ja|DanceResource Wikiへようこそ
** Introduction_to_Conscious_Dance/ja|コンシャス・ダンス入門
** Core_Methods_and_Techniques/ja|中核となる方法と技法
** Curated_Resource_Library/ja|厳選されたリソースライブラリ
** Benefits_of_Conscious_Dance/ja|コンシャス・ダンスの利点
** Scientific_Research_and_Evidence/ja|科学的研究と証拠
** Historical_and_Cultural_Context/ja|歴史的・文化的背景
** Conscious_Dance_Practices/ja|確立されたコンシャス・ダンスの実践
** Community_and_Global_Collaboration/ja|コミュニティとグローバルな協働
** Future_Directions_and_Vision/ja|将来の方向性とビジョン
** Appendices/ja|付録
** recentchanges-url|recentchanges
** Join_Our_Community/ja|コミュニティに参加する
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "ka": """* navigation
** Welcome_to_the_DanceResource_Wiki/ka|კეთილი იყოს თქვენი მობრძანება DanceResource Wiki-ზე
** Introduction_to_Conscious_Dance/ka|ცნობიერი ცეკვის შესავალი
** Core_Methods_and_Techniques/ka|ძირითადი მეთოდები და ტექნიკები
** Curated_Resource_Library/ka|კურირებული რესურსების ბიბლიოთეკა
** Benefits_of_Conscious_Dance/ka|ცნობიერი ცეკვის სარგებელი
** Scientific_Research_and_Evidence/ka|სამეცნიერო კვლევა და მტკიცებულებები
** Historical_and_Cultural_Context/ka|ისტორიული და კულტურული კონტექსტი
** Conscious_Dance_Practices/ka|დამკვიდრებული ცნობიერი ცეკვის პრაქტიკები
** Community_and_Global_Collaboration/ka|საზოგადოება და გლობალური თანამშრომლობა
** Future_Directions_and_Vision/ka|მომავალი მიმართულებები და ხედვა
** Appendices/ka|დანართები
** recentchanges-url|recentchanges
** Join_Our_Community/ka|შემოუერთდით საზოგადოებას
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "ro": """* navigation
** Welcome_to_the_DanceResource_Wiki/ro|Bine ați venit la DanceResource Wiki
** Introduction_to_Conscious_Dance/ro|Introducere în dansul conștient
** Core_Methods_and_Techniques/ro|Metode și tehnici de bază
** Curated_Resource_Library/ro|Bibliotecă de resurse curate
** Benefits_of_Conscious_Dance/ro|Beneficiile dansului conștient
** Scientific_Research_and_Evidence/ro|Cercetare științifică și dovezi
** Historical_and_Cultural_Context/ro|Context istoric și cultural
** Conscious_Dance_Practices/ro|Practici consacrate de dans conștient
** Community_and_Global_Collaboration/ro|Comunitate și colaborare globală
** Future_Directions_and_Vision/ro|Direcții viitoare și viziune
** Appendices/ro|Anexe
** recentchanges-url|recentchanges
** Join_Our_Community/ro|Alăturați-vă comunității
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "sl": """* navigation
** Welcome_to_the_DanceResource_Wiki/sl|Dobrodošli na DanceResource Wiki
** Introduction_to_Conscious_Dance/sl|Uvod v zavestni ples
** Core_Methods_and_Techniques/sl|Osnovne metode in tehnike
** Curated_Resource_Library/sl|Knjižnica izbranih virov
** Benefits_of_Conscious_Dance/sl|Prednosti zavestnega plesa
** Scientific_Research_and_Evidence/sl|Znanstvene raziskave in dokazi
** Historical_and_Cultural_Context/sl|Zgodovinski in kulturni kontekst
** Conscious_Dance_Practices/sl|Uveljavljene prakse zavestnega plesa
** Community_and_Global_Collaboration/sl|Skupnost in globalno sodelovanje
** Future_Directions_and_Vision/sl|Prihodnje smeri in vizija
** Appendices/sl|Dodatki
** recentchanges-url|recentchanges
** Join_Our_Community/sl|Pridružite se skupnosti
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "lb": """* navigation
** Welcome_to_the_DanceResource_Wiki/lb|Wëllkomm op der DanceResource Wiki
** Introduction_to_Conscious_Dance/lb|Aféierung an de bewosste Danz
** Core_Methods_and_Techniques/lb|Grondleeënd Methoden an Techniken
** Curated_Resource_Library/lb|Kuréiert Ressourcebibliothéik
** Benefits_of_Conscious_Dance/lb|Virdeeler vum bewosste Danz
** Scientific_Research_and_Evidence/lb|Wëssenschaftlech Fuerschung an Evidenz
** Historical_and_Cultural_Context/lb|Historeschen a kulturelle Kontext
** Conscious_Dance_Practices/lb|Etabléiert Praxis vum bewosste Danz
** Community_and_Global_Collaboration/lb|Gemeinschaft a global Zesummenaarbecht
** Future_Directions_and_Vision/lb|Zukünfteg Richtungen a Visioun
** Appendices/lb|Annexen
** recentchanges-url|recentchanges
** Join_Our_Community/lb|Maach mat an der Gemeinschaft
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "th": """* navigation
** Welcome_to_the_DanceResource_Wiki/th|ยินดีต้อนรับสู่ DanceResource Wiki
** Introduction_to_Conscious_Dance/th|บทนำสู่การเต้นอย่างมีสติ
** Core_Methods_and_Techniques/th|วิธีการและเทคนิคหลัก
** Curated_Resource_Library/th|คลังทรัพยากรที่คัดสรร
** Benefits_of_Conscious_Dance/th|ประโยชน์ของการเต้นอย่างมีสติ
** Scientific_Research_and_Evidence/th|งานวิจัยทางวิทยาศาสตร์และหลักฐาน
** Historical_and_Cultural_Context/th|บริบททางประวัติศาสตร์และวัฒนธรรม
** Conscious_Dance_Practices/th|แนวปฏิบัติการเต้นอย่างมีสติที่ได้รับการยอมรับ
** Community_and_Global_Collaboration/th|ชุมชนและความร่วมมือระดับโลก
** Future_Directions_and_Vision/th|ทิศทางในอนาคตและวิสัยทัศน์
** Appendices/th|ภาคผนวก
** recentchanges-url|recentchanges
** Join_Our_Community/th|เข้าร่วมชุมชน
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "is": """* navigation
** Welcome_to_the_DanceResource_Wiki/is|Velkomin á DanceResource Wiki
** Introduction_to_Conscious_Dance/is|Inngangur að meðvituðum dansi
** Core_Methods_and_Techniques/is|Grunnaðferðir og tækni
** Curated_Resource_Library/is|Safn valinna auðlinda
** Benefits_of_Conscious_Dance/is|Ávinningur meðvitaðs dans
** Scientific_Research_and_Evidence/is|Vísindarannsóknir og gögn
** Historical_and_Cultural_Context/is|Sögulegt og menningarlegt samhengi
** Conscious_Dance_Practices/is|Rótgrónar aðferðir meðvitaðs dans
** Community_and_Global_Collaboration/is|Samfélag og alþjóðlegt samstarf
** Future_Directions_and_Vision/is|Framtíðarstefnur og sýn
** Appendices/is|Viðaukar
** recentchanges-url|recentchanges
** Join_Our_Community/is|Taktu þátt í samfélaginu
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "vi": """* navigation
** Welcome_to_the_DanceResource_Wiki/vi|Chào mừng đến với DanceResource Wiki
** Introduction_to_Conscious_Dance/vi|Giới thiệu về khiêu vũ có ý thức
** Core_Methods_and_Techniques/vi|Phương pháp và kỹ thuật cốt lõi
** Curated_Resource_Library/vi|Thư viện tài nguyên được tuyển chọn
** Benefits_of_Conscious_Dance/vi|Lợi ích của khiêu vũ có ý thức
** Scientific_Research_and_Evidence/vi|Nghiên cứu khoa học và bằng chứng
** Historical_and_Cultural_Context/vi|Bối cảnh lịch sử và văn hóa
** Conscious_Dance_Practices/vi|Thực hành khiêu vũ có ý thức đã được thiết lập
** Community_and_Global_Collaboration/vi|Cộng đồng và hợp tác toàn cầu
** Future_Directions_and_Vision/vi|Định hướng tương lai và tầm nhìn
** Appendices/vi|Phụ lục
** recentchanges-url|recentchanges
** Join_Our_Community/vi|Tham gia cộng đồng
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "zu": """* navigation
** Welcome_to_the_DanceResource_Wiki/zu|Siyakwamukela ku-DanceResource Wiki
** Introduction_to_Conscious_Dance/zu|Isingeniso sokudansa okuqaphelayo
** Core_Methods_and_Techniques/zu|Izindlela nezindlela eziyisisekelo
** Curated_Resource_Library/zu|Umtapo wezinsiza okhethiwe
** Benefits_of_Conscious_Dance/zu|Izinzuzo zokudansa okuqaphelayo
** Scientific_Research_and_Evidence/zu|Ucwaningo lwesayensi nobufakazi
** Historical_and_Cultural_Context/zu|Umlando nomongo wamasiko
** Conscious_Dance_Practices/zu|Izindlela ezimisiwe zokudansa okuqaphelayo
** Community_and_Global_Collaboration/zu|Umphakathi nokubambisana komhlaba
** Future_Directions_and_Vision/zu|Izindlela zesikhathi esizayo nombono
** Appendices/zu|Izinamathiselo
** recentchanges-url|recentchanges
** Join_Our_Community/zu|Joyina umphakathi
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "zh": """* navigation
** Welcome_to_the_DanceResource_Wiki/zh|欢迎来到 DanceResource Wiki
** Introduction_to_Conscious_Dance/zh|意识舞蹈简介
** Core_Methods_and_Techniques/zh|核心方法与技巧
** Curated_Resource_Library/zh|精选资源库
** Benefits_of_Conscious_Dance/zh|意识舞蹈的益处
** Scientific_Research_and_Evidence/zh|科学研究与证据
** Historical_and_Cultural_Context/zh|历史与文化背景
** Conscious_Dance_Practices/zh|已建立的意识舞蹈实践
** Community_and_Global_Collaboration/zh|社区与全球协作
** Future_Directions_and_Vision/zh|未来方向与愿景
** Appendices/zh|附录
** recentchanges-url|recentchanges
** Join_Our_Community/zh|加入社区
* SEARCH
* TOOLBOX
* LANGUAGES
""",
}


def normalize_wikitext(text: str) -> str:
    normalized = text.replace("\r\n", "\n").rstrip()
    return f"{normalized}\n"


def update_sidebar(lang: str, client: MediaWikiClient, summary: str, force: bool) -> bool:
    if lang not in SIDEBAR_BY_LANG:
        raise KeyError(f"Unsupported language code: {lang}")
    title = f"MediaWiki:Sidebar/{lang}"
    desired = normalize_wikitext(SIDEBAR_BY_LANG[lang])
    if not force:
        try:
            current, _, _ = client.get_page_wikitext(title)
        except Exception:
            current = ""
        if normalize_wikitext(current) == desired:
            log.info("no changes for %s", title)
            return False
    revid = client.edit(title, desired, summary=summary, bot=True)
    log.info("updated %s (revid=%s)", title, revid)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Update localized MediaWiki:Sidebar pages.")
    parser.add_argument(
        "--lang",
        action="append",
        dest="langs",
        help="Language code to update (repeatable). Defaults to all configured languages.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print changes without editing.")
    parser.add_argument(
        "--summary",
        default="Update localized sidebar navigation",
        help="Edit summary to use for updates.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force edits even if current content matches.",
    )
    args = parser.parse_args()

    configure_logging()
    cfg = load_config()
    session = __import__("requests").Session()
    client = MediaWikiClient(cfg.mw_api_url, cfg.mw_user_agent, session)
    client.login(cfg.mw_username, cfg.mw_password)

    langs = sorted(set(args.langs or SIDEBAR_BY_LANG.keys()))
    if not langs:
        log.warning("no languages specified")
        return

    if args.dry_run:
        for lang in langs:
            title = f"MediaWiki:Sidebar/{lang}"
            print(f"== {title} ==")
            print(normalize_wikitext(SIDEBAR_BY_LANG[lang]))
        return

    updated = 0
    for lang in langs:
        changed = update_sidebar(lang, client, summary=args.summary, force=args.force)
        if changed:
            updated += 1
    log.info("sidebar updates complete: %s/%s changed", updated, len(langs))


if __name__ == "__main__":
    main()
