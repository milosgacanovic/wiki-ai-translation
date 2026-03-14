from __future__ import annotations

import argparse
import logging

from .config import load_config
from .logging import configure_logging
from .mediawiki import MediaWikiClient

log = logging.getLogger("bot.update_sidebar")


SIDEBAR_BY_LANG: dict[str, str] = {
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|ابحث عن الفعاليات
** https://events.danceresource.org/hosts/|ابحث عن المعلمين
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Najít akce
** https://events.danceresource.org/hosts/|Najít učitele
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Find begivenheder
** https://events.danceresource.org/hosts/|Find lærere
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "de": """* navigation
** Welcome_to_the_DanceResource_Wiki/de|Willkommen im DanceResource Wiki
** Introduction_to_Conscious_Dance/de|Einführung in den bewussten Tanz
** Core_Methods_and_Techniques/de|Kernmethoden und Techniken
** Curated_Resource_Library/de|Kuratierte Ressourcenbibliothek
** Benefits_of_Conscious_Dance/de|Vorteile des bewussten Tanzes
** Scientific_Research_and_Evidence/de|Wissenschaftliche Forschung und Belege
** Historical_and_Cultural_Context/de|Historischer und kultureller Kontext
** Conscious_Dance_Practices/de|Etablierte Praxisformen des bewussten Tanzes
** Community_and_Global_Collaboration/de|Gemeinschaft und globale Zusammenarbeit
** Future_Directions_and_Vision/de|Zukünftige Richtungen und Vision
** Appendices/de|Anhänge
** recentchanges-url|recentchanges
** Join_Our_Community/de|Der Gemeinschaft beitreten
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Veranstaltungen finden
** https://events.danceresource.org/hosts/|Lehrende finden
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Βρείτε εκδηλώσεις
** https://events.danceresource.org/hosts/|Βρείτε δασκάλους
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "es": """* navigation
** Welcome_to_the_DanceResource_Wiki/es|Bienvenidos a DanceResource Wiki
** Introduction_to_Conscious_Dance/es|Introducción a la danza consciente
** Core_Methods_and_Techniques/es|Métodos y técnicas fundamentales
** Curated_Resource_Library/es|Biblioteca de recursos curados
** Benefits_of_Conscious_Dance/es|Beneficios de la danza consciente
** Scientific_Research_and_Evidence/es|Investigación científica y evidencias
** Historical_and_Cultural_Context/es|Contexto histórico y cultural
** Conscious_Dance_Practices/es|Prácticas establecidas de danza consciente
** Community_and_Global_Collaboration/es|Comunidad y colaboración global
** Future_Directions_and_Vision/es|Direcciones futuras y visión
** Appendices/es|Apéndices
** recentchanges-url|recentchanges
** Join_Our_Community/es|Únete a la comunidad
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Encontrar eventos
** https://events.danceresource.org/hosts/|Encontrar profesores
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Etsi tapahtumia
** https://events.danceresource.org/hosts/|Etsi opettajia
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "fr": """* navigation
** Welcome_to_the_DanceResource_Wiki/fr|Bienvenue sur DanceResource Wiki
** Introduction_to_Conscious_Dance/fr|Introduction à la danse consciente
** Core_Methods_and_Techniques/fr|Méthodes et techniques fondamentales
** Curated_Resource_Library/fr|Bibliothèque de ressources sélectionnées
** Benefits_of_Conscious_Dance/fr|Bienfaits de la danse consciente
** Scientific_Research_and_Evidence/fr|Recherche scientifique et preuves
** Historical_and_Cultural_Context/fr|Contexte historique et culturel
** Conscious_Dance_Practices/fr|Pratiques établies de danse consciente
** Community_and_Global_Collaboration/fr|Communauté et collaboration mondiale
** Future_Directions_and_Vision/fr|Directions futures et vision
** Appendices/fr|Annexes
** recentchanges-url|recentchanges
** Join_Our_Community/fr|Rejoindre la communauté
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Trouver des événements
** https://events.danceresource.org/hosts/|Trouver des enseignants
* SEARCH
* TOOLBOX
* LANGUAGES
""",
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|מצא אירועים
** https://events.danceresource.org/hosts/|מצא מדריכים
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|कार्यक्रम खोजें
** https://events.danceresource.org/hosts/|शिक्षक खोजें
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Pronađi događaje
** https://events.danceresource.org/hosts/|Pronađi učitelje
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Események keresése
** https://events.danceresource.org/hosts/|Oktatók keresése
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Temukan Acara
** https://events.danceresource.org/hosts/|Temukan Pengajar
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Finna viðburði
** https://events.danceresource.org/hosts/|Finna kennara
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "it": """* navigation
** Welcome_to_the_DanceResource_Wiki/it|Benvenuti su DanceResource Wiki
** Introduction_to_Conscious_Dance/it|Introduzione alla danza consapevole
** Core_Methods_and_Techniques/it|Metodi e tecniche fondamentali
** Curated_Resource_Library/it|Biblioteca di risorse selezionate
** Benefits_of_Conscious_Dance/it|Benefici della danza consapevole
** Scientific_Research_and_Evidence/it|Ricerca scientifica e prove
** Historical_and_Cultural_Context/it|Contesto storico e culturale
** Conscious_Dance_Practices/it|Pratiche consolidate di danza consapevole
** Community_and_Global_Collaboration/it|Comunità e collaborazione globale
** Future_Directions_and_Vision/it|Direzioni future e visione
** Appendices/it|Appendici
** recentchanges-url|recentchanges
** Join_Our_Community/it|Unisciti alla comunità
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Trovare eventi
** https://events.danceresource.org/hosts/|Trovare insegnanti
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|イベントを探す
** https://events.danceresource.org/hosts/|講師を探す
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|ღონისძიებების ძიება
** https://events.danceresource.org/hosts/|მასწავლებლების ძიება
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|이벤트 찾기
** https://events.danceresource.org/hosts/|강사 찾기
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Evenementer fannen
** https://events.danceresource.org/hosts/|Léierpersounen fannen
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "nb": """* navigation
** Welcome_to_the_DanceResource_Wiki/nb|Velkommen til DanceResource Wiki
** Introduction_to_Conscious_Dance/nb|Introduksjon til bevisst dans
** Core_Methods_and_Techniques/nb|Grunnleggende metoder og teknikker
** Curated_Resource_Library/nb|Kurert ressursbibliotek
** Benefits_of_Conscious_Dance/nb|Fordeler med bevisst dans
** Scientific_Research_and_Evidence/nb|Vitenskapelig forskning og evidens
** Historical_and_Cultural_Context/nb|Historisk og kulturell kontekst
** Conscious_Dance_Practices/nb|Etablerte praksiser for bevisst dans
** Community_and_Global_Collaboration/nb|Fellesskap og globalt samarbeid
** Future_Directions_and_Vision/nb|Fremtidige retninger og visjon
** Appendices/nb|Vedlegg
** recentchanges-url|recentchanges
** Join_Our_Community/nb|Bli med i fellesskapet
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Finn arrangementer
** https://events.danceresource.org/hosts/|Finn lærere
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "nl": """* navigation
** Welcome_to_the_DanceResource_Wiki/nl|Welkom bij DanceResource Wiki
** Introduction_to_Conscious_Dance/nl|Introductie tot bewust dansen
** Core_Methods_and_Techniques/nl|Kernmethoden en technieken
** Curated_Resource_Library/nl|Samengestelde bronnenbibliotheek
** Benefits_of_Conscious_Dance/nl|Voordelen van bewust dansen
** Scientific_Research_and_Evidence/nl|Wetenschappelijk onderzoek en bewijs
** Historical_and_Cultural_Context/nl|Historische en culturele context
** Conscious_Dance_Practices/nl|Gevestigde praktijken van bewust dansen
** Community_and_Global_Collaboration/nl|Gemeenschap en wereldwijde samenwerking
** Future_Directions_and_Vision/nl|Toekomstige richtingen en visie
** Appendices/nl|Bijlagen
** recentchanges-url|recentchanges
** Join_Our_Community/nl|Word lid van de gemeenschap
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Evenementen vinden
** https://events.danceresource.org/hosts/|Leraren vinden
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Znajdź wydarzenia
** https://events.danceresource.org/hosts/|Znajdź nauczycieli
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Encontrar eventos
** https://events.danceresource.org/hosts/|Encontrar professores
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Găsește evenimente
** https://events.danceresource.org/hosts/|Găsește profesori
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "ru": """* navigation
** Welcome_to_the_DanceResource_Wiki/ru|Добро пожаловать в DanceResource Wiki
** Introduction_to_Conscious_Dance/ru|Введение в осознанный танец
** Core_Methods_and_Techniques/ru|Основные методы и техники
** Curated_Resource_Library/ru|Тематическая библиотека ресурсов
** Benefits_of_Conscious_Dance/ru|Преимущества осознанного танца
** Scientific_Research_and_Evidence/ru|Научные исследования и доказательства
** Historical_and_Cultural_Context/ru|Исторический и культурный контекст
** Conscious_Dance_Practices/ru|Устоявшиеся практики осознанного танца
** Community_and_Global_Collaboration/ru|Сообщество и глобальное сотрудничество
** Future_Directions_and_Vision/ru|Будущие направления и видение
** Appendices/ru|Приложения
** recentchanges-url|recentchanges
** Join_Our_Community/ru|Присоединяйтесь к сообществу
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Найти мероприятия
** https://events.danceresource.org/hosts/|Найти преподавателей
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Nájsť podujatia
** https://events.danceresource.org/hosts/|Nájsť učiteľov
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Poišči dogodke
** https://events.danceresource.org/hosts/|Poišči učitelje
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "sr": """* navigation
** Welcome_to_the_DanceResource_Wiki/sr|Dobrodošli na DanceResource Wiki
** Introduction_to_Conscious_Dance/sr|Uvod u svesni ples
** Core_Methods_and_Techniques/sr|Osnovne metode i tehnike
** Curated_Resource_Library/sr|Biblioteka odabranih resursa
** Benefits_of_Conscious_Dance/sr|Prednosti svesnog plesa
** Scientific_Research_and_Evidence/sr|Naučna istraživanja i dokazi
** Historical_and_Cultural_Context/sr|Istorijski i kulturni kontekst
** Conscious_Dance_Practices/sr|Utemeljene prakse svesnog plesa
** Community_and_Global_Collaboration/sr|Zajednica i globalna saradnja
** Future_Directions_and_Vision/sr|Budući pravci i vizija
** Appendices/sr|Dodaci
** recentchanges-url|recentchanges
** Join_Our_Community/sr|Pridružite se zajednici
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Pronađi događaje
** https://events.danceresource.org/hosts/|Pronađi učitelje
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Hitta evenemang
** https://events.danceresource.org/hosts/|Hitta lärare
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|ค้นหากิจกรรม
** https://events.danceresource.org/hosts/|ค้นหาครู
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "tr": """* navigation
** Welcome_to_the_DanceResource_Wiki/tr|DanceResource Wiki'ye Hoş Geldiniz
** Introduction_to_Conscious_Dance/tr|Bilinçli Dansa Giriş
** Core_Methods_and_Techniques/tr|Temel Yöntemler ve Teknikler
** Curated_Resource_Library/tr|Seçilmiş Kaynak Kütüphanesi
** Benefits_of_Conscious_Dance/tr|Bilinçli Dansın Faydaları
** Scientific_Research_and_Evidence/tr|Bilimsel Araştırma ve Kanıtlar
** Historical_and_Cultural_Context/tr|Tarihsel ve Kültürel Bağlam
** Conscious_Dance_Practices/tr|Yerleşik Bilinçli Dans Uygulamaları
** Community_and_Global_Collaboration/tr|Topluluk ve Küresel İşbirliği
** Future_Directions_and_Vision/tr|Gelecekteki Yönler ve Vizyon
** Appendices/tr|Ekler
** recentchanges-url|recentchanges
** Join_Our_Community/tr|Topluluğa Katılın
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Etkinlik Bul
** https://events.danceresource.org/hosts/|Öğretmen Bul
* SEARCH
* TOOLBOX
* LANGUAGES
""",
    "uk": """* navigation
** Welcome_to_the_DanceResource_Wiki/uk|Ласкаво просимо до DanceResource Wiki
** Introduction_to_Conscious_Dance/uk|Вступ до усвідомленого танцю
** Core_Methods_and_Techniques/uk|Основні методи та техніки
** Curated_Resource_Library/uk|Підібрана бібліотека ресурсів
** Benefits_of_Conscious_Dance/uk|Переваги усвідомленого танцю
** Scientific_Research_and_Evidence/uk|Наукові дослідження та докази
** Historical_and_Cultural_Context/uk|Історичний і культурний контекст
** Conscious_Dance_Practices/uk|Усталені практики усвідомленого танцю
** Community_and_Global_Collaboration/uk|Спільнота та глобальна співпраця
** Future_Directions_and_Vision/uk|Майбутні напрямки та бачення
** Appendices/uk|Додатки
** recentchanges-url|recentchanges
** Join_Our_Community/uk|Приєднуйтесь до спільноти
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Знайти заходи
** https://events.danceresource.org/hosts/|Знайти вчителів
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Tìm sự kiện
** https://events.danceresource.org/hosts/|Tìm giáo viên
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|查找活动
** https://events.danceresource.org/hosts/|查找教师
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
* DanceResource Network
** https://www.danceresource.org/|DanceResource.org
** https://events.danceresource.org/events/|Thola Imicimbi
** https://events.danceresource.org/hosts/|Thola Otitshela
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
