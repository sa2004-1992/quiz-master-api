"""Starter question bank (2 per category) so the site works before Gemini is configured.

Tuple format: (question, [A, B, C, D], correct_letter, explanation, difficulty)
"""
SEED = {
    "History": [
        ("Who was the first President of the United States?", ["Thomas Jefferson", "George Washington", "Abraham Lincoln", "John Adams"], "B", "George Washington served as the first U.S. President from 1789 to 1797.", "easy"),
        ("In which year was the Magna Carta sealed?", ["1066", "1215", "1492", "1588"], "B", "King John of England sealed the Magna Carta at Runnymede in 1215.", "medium"),
    ],
    "Math": [
        ("What is 12 × 12?", ["122", "124", "144", "164"], "C", "12 multiplied by 12 equals 144.", "easy"),
        ("What is the sum of the interior angles of a triangle?", ["90°", "180°", "270°", "360°"], "B", "The interior angles of any triangle on a flat plane add up to 180 degrees.", "easy"),
    ],
    "Science": [
        ("Which gas do plants absorb from the air for photosynthesis?", ["Oxygen", "Nitrogen", "Carbon dioxide", "Hydrogen"], "C", "Plants take in carbon dioxide and use sunlight and water to make glucose.", "easy"),
        ("What is the chemical symbol for gold?", ["Ag", "Au", "Gd", "Go"], "B", "Au comes from the Latin word 'aurum', meaning gold.", "medium"),
    ],
    "Space (Astronomy)": [
        ("Which planet is closest to the Sun?", ["Venus", "Earth", "Mercury", "Mars"], "C", "Mercury orbits closer to the Sun than any other planet.", "easy"),
        ("Which is the largest planet in our Solar System?", ["Saturn", "Jupiter", "Neptune", "Uranus"], "B", "Jupiter is the largest planet, more than eleven times wider than Earth.", "easy"),
    ],
    "Kannada": [
        ("ಕರ್ನಾಟಕದ ರಾಜ್ಯ ಪಕ್ಷಿ ಯಾವುದು?", ["ನವಿಲು", "ನೀಲಕಂಠ", "ಗಿಳಿ", "ಕೋಗಿಲೆ"], "B", "ನೀಲಕಂಠ (ಇಂಡಿಯನ್ ರೋಲರ್) ಕರ್ನಾಟಕದ ರಾಜ್ಯ ಪಕ್ಷಿಯಾಗಿದೆ.", "easy"),
        ("ಜೋಗ ಜಲಪಾತವು ಯಾವ ನದಿಯಿಂದ ಉಂಟಾಗಿದೆ?", ["ಕಾವೇರಿ", "ತುಂಗಭದ್ರಾ", "ಕೃಷ್ಣಾ", "ಶರಾವತಿ"], "D", "ಜೋಗ ಜಲಪಾತವು ಶರಾವತಿ ನದಿಯಿಂದ ಉಂಟಾಗಿದೆ.", "medium"),
    ],
    "English": [
        ("Which word is a synonym of 'happy'?", ["Sad", "Joyful", "Angry", "Tired"], "B", "'Joyful' means feeling great pleasure, just like 'happy'.", "easy"),
        ("What is the plural of 'child'?", ["Childs", "Childes", "Children", "Childrens"], "C", "'Children' is the irregular plural of 'child'.", "easy"),
    ],
    "Social Science": [
        ("What do we call a system of government in which leaders are elected by the people?", ["Monarchy", "Democracy", "Dictatorship", "Oligarchy"], "B", "In a democracy, citizens choose their leaders through elections.", "easy"),
        ("Which subject studies the Earth's surface, climate and people?", ["Geography", "Chemistry", "Zoology", "Algebra"], "A", "Geography studies landscapes, climates and how people interact with them.", "easy"),
    ],
    "Software": [
        ("What does IDE stand for in programming?", ["Integrated Development Environment", "Internal Data Exchange", "Interactive Design Editor", "Integrated Debug Engine"], "A", "An IDE combines a code editor, build tools and a debugger in one application.", "easy"),
        ("Which of these is a distributed version control system?", ["Git", "Excel", "Photoshop", "Notepad"], "A", "Git tracks source-code changes and lets many developers collaborate.", "easy"),
    ],
    "Hardware": [
        ("What does CPU stand for?", ["Central Processing Unit", "Computer Power Unit", "Central Program Utility", "Core Processing Unit"], "A", "The CPU is the main processor that executes program instructions.", "easy"),
        ("Which of these components provides permanent storage?", ["RAM", "Cache", "Solid-state drive", "CPU register"], "C", "An SSD keeps data when power is off, unlike RAM, cache or registers.", "medium"),
    ],
    "Artificial Intelligence (AI)": [
        ("What does AI stand for?", ["Automated Internet", "Artificial Intelligence", "Advanced Interface", "Applied Integration"], "B", "AI stands for Artificial Intelligence.", "easy"),
        ("Who is credited with coining the term 'artificial intelligence'?", ["Alan Turing", "John McCarthy", "Elon Musk", "Tim Berners-Lee"], "B", "John McCarthy introduced the term for the 1956 Dartmouth workshop.", "medium"),
    ],
    "Machine Learning (ML)": [
        ("Which type of machine learning uses labelled training data?", ["Supervised learning", "Unsupervised learning", "Reinforcement learning", "Quantum learning"], "A", "Supervised learning trains on examples that already have correct labels.", "easy"),
        ("What is 'overfitting' in machine learning?", ["A model that learns the training data too closely and generalises poorly", "A model that trains too quickly", "A model with too few features", "A model that never converges"], "A", "An overfitted model memorises noise in the training data and performs badly on new data.", "medium"),
    ],
    "General Knowledge (GK)": [
        ("What is the capital of Australia?", ["Sydney", "Melbourne", "Canberra", "Perth"], "C", "Canberra is Australia's capital city.", "easy"),
        ("Which is the largest ocean on Earth?", ["Atlantic", "Indian", "Arctic", "Pacific"], "D", "The Pacific Ocean covers more area than all of Earth's land combined.", "easy"),
    ],
    "Aptitude": [
        ("A train travels 60 km every hour. How far will it travel in 3 hours at the same speed?", ["120 km", "150 km", "180 km", "210 km"], "C", "Distance = speed × time = 60 × 3 = 180 km.", "easy"),
        ("What is 25% of 200?", ["25", "40", "50", "75"], "C", "25% is one quarter, and a quarter of 200 is 50.", "easy"),
    ],
    "Web Development": [
        ("Which language is mainly used to add interactivity to web pages in the browser?", ["Python", "JavaScript", "SQL", "C++"], "B", "JavaScript runs in the browser and controls page behaviour.", "easy"),
        ("Which HTTP method is normally used to retrieve data from a server?", ["GET", "DELETE", "PUT", "TRACE"], "A", "GET requests fetch a resource without changing it.", "easy"),
    ],
    "Puzzles": [
        ("I have keys but open no locks and I have a space but no room. What am I?", ["A piano", "A keyboard", "A map", "A house"], "B", "A computer keyboard has keys and a space bar, but no locks or rooms.", "easy"),
        ("What has hands but cannot clap?", ["A clock", "A statue", "A glove", "A tree"], "A", "A clock has hour and minute hands.", "easy"),
    ],
    "Chess": [
        ("How many squares are there on a standard chessboard?", ["48", "56", "64", "72"], "C", "A chessboard has 8 rows and 8 columns, so 64 squares.", "easy"),
        ("Which chess piece moves in an L-shape?", ["Bishop", "Rook", "Knight", "Queen"], "C", "The knight moves two squares in one direction and one square at a right angle.", "easy"),
    ],
    "Cricket": [
        ("How many players of a cricket team are on the field at one time?", ["9", "10", "11", "12"], "C", "Each side fields eleven players.", "easy"),
        ("How many legal balls are bowled in a standard over?", ["4", "5", "6", "8"], "C", "A standard over consists of six legal deliveries.", "easy"),
    ],
    "Health & Human Body": [
        ("Which organ pumps blood around the human body?", ["Liver", "Heart", "Kidney", "Lung"], "B", "The heart pumps blood through the circulatory system.", "easy"),
        ("How many bones does a typical adult human body have?", ["106", "206", "306", "406"], "B", "An adult human skeleton typically has 206 bones.", "medium"),
    ],
    "Olympics": [
        ("How often are the Summer Olympic Games normally held?", ["Every year", "Every two years", "Every four years", "Every five years"], "C", "The Summer Olympics take place every four years.", "easy"),
        ("How many rings are in the Olympic symbol?", ["Four", "Five", "Six", "Seven"], "B", "The five interlocking rings represent the five regions united by Olympism.", "easy"),
    ],
    "Formula": [
        ("In Formula 1, what does the chequered flag signal?", ["The end of a race or session", "A mechanical failure", "A pit stop", "A safety car period"], "A", "The chequered flag is waved to mark the finish of a race or session.", "easy"),
        ("In which country is the Monza circuit located?", ["France", "Spain", "Italy", "Germany"], "C", "Monza is Italy's historic Formula 1 circuit near Milan.", "medium"),
    ],
    "IPL": [
        ("In which year was the first Indian Premier League season played?", ["2006", "2008", "2010", "2012"], "B", "The inaugural IPL season took place in 2008.", "easy"),
        ("Which team won the inaugural IPL season?", ["Chennai Super Kings", "Mumbai Indians", "Rajasthan Royals", "Deccan Chargers"], "C", "Rajasthan Royals won the first IPL season in 2008.", "medium"),
    ],
    "Operating Systems": [
        ("Which operating system kernel was first released by Linus Torvalds in 1991?", ["Linux", "Windows", "Unix", "Minix"], "A", "Linus Torvalds released the first version of the Linux kernel in 1991.", "medium"),
        ("What is the job of a CPU scheduler in an operating system?", ["Deciding which process runs on the CPU next", "Encrypting files", "Rendering web pages", "Assigning IP addresses"], "A", "The scheduler chooses which ready process gets the CPU and for how long.", "medium"),
    ],
    "Python": [
        ("Which keyword is used to define a function in Python?", ["func", "define", "def", "function"], "C", "Python functions are defined with the 'def' keyword.", "easy"),
        ("Which of these Python data types is immutable?", ["list", "dict", "set", "tuple"], "D", "A tuple cannot be changed after it is created.", "medium"),
    ],
    "Java": [
        ("Which keyword is used for class inheritance in Java?", ["inherits", "extends", "super", "import"], "B", "A Java class inherits from another class using 'extends'.", "easy"),
        ("Which company originally developed Java?", ["Microsoft", "Sun Microsystems", "Apple", "IBM"], "B", "Java was created at Sun Microsystems, later acquired by Oracle.", "medium"),
    ],
    "Algorithms & Data Structures": [
        ("Which data structure follows First-In-First-Out (FIFO) order?", ["Stack", "Queue", "Tree", "Graph"], "B", "A queue removes elements in the same order in which they were added.", "easy"),
        ("What is the time complexity of binary search on a sorted array?", ["O(n)", "O(log n)", "O(n log n)", "O(1)"], "B", "Binary search halves the search range each step, giving O(log n).", "medium"),
    ],
    "Computer Basics": [
        ("What does RAM stand for?", ["Random Access Memory", "Read Access Module", "Rapid Application Memory", "Run Active Memory"], "A", "RAM is the computer's fast, temporary working memory.", "easy"),
        ("Which keyboard shortcut is commonly used to copy selected text on Windows?", ["Ctrl + C", "Ctrl + V", "Ctrl + X", "Ctrl + Z"], "A", "Ctrl + C copies the selection; Ctrl + V pastes it.", "easy"),
    ],
    "Animals": [
        ("What is the largest living land animal?", ["Rhinoceros", "African elephant", "Giraffe", "Hippopotamus"], "B", "The African elephant is the largest living land animal.", "easy"),
        ("Which mammal is capable of true flight?", ["Flying squirrel", "Bat", "Sugar glider", "Colugo"], "B", "Bats are the only mammals that can truly fly; the others only glide.", "medium"),
    ],
    "Birds": [
        ("Which bird is the national bird of India?", ["Sparrow", "Indian peafowl", "Eagle", "Parrot"], "B", "The Indian peafowl (peacock) is India's national bird.", "easy"),
        ("Which of these birds cannot fly?", ["Ostrich", "Crow", "Pigeon", "Owl"], "A", "The ostrich is a flightless bird.", "easy"),
    ],
    "Plants": [
        ("Which part of a plant mainly absorbs water from the soil?", ["Leaves", "Flowers", "Roots", "Fruits"], "C", "Roots absorb water and minerals from the soil.", "easy"),
        ("Which pigment gives plants their green colour?", ["Melanin", "Chlorophyll", "Haemoglobin", "Carotene"], "B", "Chlorophyll absorbs light for photosynthesis and appears green.", "easy"),
    ],
    "General Trivia": [
        ("How many days are there in a leap year?", ["364", "365", "366", "367"], "C", "A leap year has 366 days because February gets an extra day.", "easy"),
        ("Which planet is nicknamed the Red Planet?", ["Mars", "Venus", "Jupiter", "Mercury"], "A", "Iron oxide on its surface gives Mars its reddish colour.", "easy"),
    ],
    "Oceans & Marine Life": [
        ("What is the deepest known point in Earth's oceans called?", ["Challenger Deep", "Sunda Trench", "Puerto Rico Trench", "Tonga Trench"], "A", "Challenger Deep, in the Mariana Trench, is the deepest known point in the oceans.", "medium"),
        ("Which is the largest animal living in the oceans?", ["Great white shark", "Blue whale", "Giant squid", "Orca"], "B", "The blue whale is the largest animal known to have lived.", "easy"),
    ],
    "Mountains & Rivers (India Only)": [
        ("Which is the highest mountain peak in India?", ["Nanda Devi", "Kangchenjunga", "Kamet", "Saser Kangri"], "B", "Kangchenjunga (8,586 m), on the Sikkim–Nepal border, is India's highest peak.", "medium"),
        ("Which is the longest river of peninsular India?", ["Krishna", "Godavari", "Kaveri", "Narmada"], "B", "The Godavari, about 1,465 km long, is the longest river of peninsular India.", "medium"),
    ],
    "Travel & Tourism": [
        ("In which Indian city is the Taj Mahal located?", ["Delhi", "Jaipur", "Agra", "Lucknow"], "C", "The Taj Mahal stands on the banks of the Yamuna river in Agra.", "easy"),
        ("Which country is home to the Eiffel Tower?", ["Italy", "France", "Belgium", "Spain"], "B", "The Eiffel Tower is in Paris, France.", "easy"),
    ],
    "Countries & Capitals": [
        ("What is the capital of Japan?", ["Osaka", "Kyoto", "Tokyo", "Nagoya"], "C", "Tokyo is the capital of Japan.", "easy"),
        ("What is the capital of Canada?", ["Toronto", "Ottawa", "Vancouver", "Montreal"], "B", "Ottawa is the capital of Canada.", "medium"),
    ],
    "Board Games": [
        ("In which board game do players buy properties and collect rent?", ["Monopoly", "Ludo", "Snakes and Ladders", "Scrabble"], "A", "Monopoly is about buying, trading and developing properties.", "easy"),
        ("In Scrabble, players score points by forming what?", ["Words", "Numbers", "Shapes", "Melodies"], "A", "Scrabble players place lettered tiles to form words.", "easy"),
    ],
    "Number Puzzles": [
        ("What comes next in the sequence 2, 4, 8, 16, ...?", ["18", "24", "32", "64"], "C", "Each term doubles the previous one, so the next term is 32.", "easy"),
        ("What is the smallest prime number greater than 7?", ["9", "10", "11", "13"], "C", "9 and 10 are not prime; 11 is the next prime after 7.", "easy"),
    ],
    "Languages": [
        ("Which language has the most native speakers in the world?", ["English", "Mandarin Chinese", "Spanish", "Hindi"], "B", "Mandarin Chinese has the largest number of native speakers.", "medium"),
        ("Which script is used to write Hindi?", ["Devanagari", "Latin", "Cyrillic", "Arabic"], "A", "Hindi is written in the Devanagari script.", "easy"),
    ],
    "Famous People": [
        ("Who painted the Mona Lisa?", ["Vincent van Gogh", "Pablo Picasso", "Leonardo da Vinci", "Michelangelo"], "C", "Leonardo da Vinci painted the Mona Lisa in the early 1500s.", "easy"),
        ("Who is known as the 'Father of the Nation' in India?", ["Jawaharlal Nehru", "Mahatma Gandhi", "Sardar Patel", "Subhas Chandra Bose"], "B", "Mahatma Gandhi is honoured as the Father of the Nation.", "easy"),
    ],
    "Mobile & Apps": [
        ("Which company develops the Android operating system?", ["Apple", "Microsoft", "Google", "Samsung"], "C", "Android is developed by Google.", "easy"),
        ("Which operating system runs on Apple's iPhone?", ["Android", "iOS", "Windows Phone", "HarmonyOS"], "B", "The iPhone runs Apple's iOS.", "easy"),
    ],
    "Brain Teasers": [
        ("A farmer has 17 sheep and all but 9 run away. How many sheep are left?", ["8", "9", "17", "0"], "B", "'All but 9' means 9 sheep remain.", "medium"),
        ("What is full of holes but still holds water?", ["A net", "A sponge", "A bucket", "A sieve"], "B", "A sponge is full of holes yet holds water.", "easy"),
    ],
    "Mental Math": [
        ("What is 15 × 6?", ["80", "85", "90", "96"], "C", "15 × 6 = 90.", "easy"),
        ("What is 144 ÷ 12?", ["10", "11", "12", "14"], "C", "12 × 12 = 144, so 144 ÷ 12 = 12.", "easy"),
    ],
    "Cinema": [
        ("Who directed the 1997 film Titanic?", ["Steven Spielberg", "James Cameron", "Christopher Nolan", "Ridley Scott"], "B", "James Cameron directed Titanic (1997).", "easy"),
        ("Who is known as the 'Father of Indian Cinema'?", ["Raj Kapoor", "Satyajit Ray", "Dadasaheb Phalke", "Guru Dutt"], "C", "Dadasaheb Phalke made India's first full-length feature film, Raja Harishchandra (1913).", "medium"),
    ],
    "Photography": [
        ("In photography, what does the ISO setting control?", ["Sensor sensitivity to light", "Lens focal length", "Shutter colour", "Flash duration only"], "A", "ISO controls how sensitive the camera sensor is to light.", "medium"),
        ("What does a wider aperture (lower f-number) do?", ["Lets in more light", "Lets in less light", "Increases zoom", "Stops the shutter"], "A", "A wider aperture admits more light to the sensor.", "medium"),
    ],
    "UI/UX Design": [
        ("What does UX stand for?", ["User Experience", "Universal Exchange", "User Extension", "Unified Execution"], "A", "UX stands for User Experience.", "easy"),
        ("Which tool is widely used for collaborative interface design and prototyping?", ["Figma", "Wireshark", "Postman", "Docker"], "A", "Figma is a popular collaborative interface design tool.", "easy"),
    ],
    "HTML": [
        ("Which HTML tag is used to create a hyperlink?", ["<link>", "<a>", "<href>", "<url>"], "B", "The <a> (anchor) element creates hyperlinks.", "easy"),
        ("Which HTML element defines the largest heading?", ["<h6>", "<head>", "<h1>", "<title>"], "C", "<h1> is the highest-level, largest heading.", "easy"),
    ],
    "CSS": [
        ("What does CSS stand for?", ["Cascading Style Sheets", "Creative Style System", "Computer Style Syntax", "Colourful Style Sheets"], "A", "CSS stands for Cascading Style Sheets.", "easy"),
        ("Which CSS property changes the text colour of an element?", ["font-style", "color", "text-align", "background"], "B", "The 'color' property sets the text colour.", "easy"),
    ],
    "Scientists": [
        ("Who developed the theory of general relativity?", ["Isaac Newton", "Albert Einstein", "Niels Bohr", "Galileo Galilei"], "B", "Albert Einstein published general relativity in 1915.", "easy"),
        ("Who discovered penicillin in 1928?", ["Louis Pasteur", "Alexander Fleming", "Marie Curie", "Robert Koch"], "B", "Alexander Fleming noticed mould killing bacteria and discovered penicillin.", "medium"),
    ],
    "Law & Constitution": [
        ("Who chaired the Drafting Committee of the Indian Constitution?", ["B. R. Ambedkar", "Jawaharlal Nehru", "Rajendra Prasad", "Sardar Patel"], "A", "Dr B. R. Ambedkar chaired the Drafting Committee.", "medium"),
        ("On which date did the Constitution of India come into effect?", ["15 August 1947", "26 January 1950", "26 November 1949", "2 October 1950"], "B", "The Constitution came into effect on 26 January 1950, celebrated as Republic Day.", "medium"),
    ],
    "Indian History": [
        ("Who founded the Maurya Empire?", ["Ashoka", "Chandragupta Maurya", "Bindusara", "Harsha"], "B", "Chandragupta Maurya founded the Maurya Empire around 321 BCE.", "medium"),
        ("In which year did India gain independence from British rule?", ["1942", "1945", "1947", "1950"], "C", "India became independent on 15 August 1947.", "easy"),
    ],
    "World History": [
        ("Which ancient civilization built the pyramids of Giza?", ["Romans", "Egyptians", "Greeks", "Persians"], "B", "Ancient Egyptians built the Giza pyramids as royal tombs.", "easy"),
        ("In which year did the French Revolution begin?", ["1689", "1776", "1789", "1815"], "C", "The French Revolution began in 1789.", "medium"),
    ],
    "Environment": [
        ("Which gas is the largest contributor to human-caused global warming?", ["Carbon dioxide", "Helium", "Argon", "Neon"], "A", "Carbon dioxide from burning fossil fuels is the largest human-caused contributor.", "medium"),
        ("What do the three Rs of waste management stand for?", ["Reduce, Reuse, Recycle", "Remove, Replace, Repair", "Refill, Rebuild, Recover", "Rinse, Rotate, Repeat"], "A", "The three Rs are Reduce, Reuse and Recycle.", "easy"),
    ],
    "Technology": [
        ("Who is credited with inventing the World Wide Web?", ["Bill Gates", "Tim Berners-Lee", "Steve Jobs", "Larry Page"], "B", "Tim Berners-Lee invented the World Wide Web in 1989–1991.", "medium"),
        ("What does GPS stand for?", ["Global Positioning System", "General Phone Service", "Global Planet Scanner", "Geographic Packet Signal"], "A", "GPS stands for Global Positioning System.", "easy"),
    ],
    "Logical Reasoning": [
        ("All roses are flowers, and all flowers need water. Which conclusion must be true?", ["Roses need water", "Roses are animals", "Water needs roses", "Some roses are not flowers"], "A", "If every rose is a flower and every flower needs water, then roses need water.", "medium"),
        ("Which one is the odd one out: Apple, Banana, Carrot, Mango?", ["Apple", "Banana", "Carrot", "Mango"], "C", "Carrot is a vegetable; the others are fruits.", "easy"),
    ],
    "Funny Questions": [
        ("What do you call a fake noodle?", ["An impasta", "A spaghetto", "A pretend-ni", "A noodlet"], "A", "It is a classic pun: 'impasta' sounds like 'imposter'.", "easy"),
        ("In the classic joke, why did the scarecrow win an award?", ["He was outstanding in his field", "He scared every crow", "He never moved", "He grew the biggest corn"], "A", "The pun is that he was 'outstanding in his field'.", "easy"),
    ],
    "Crazy Facts": [
        ("How many hearts does an octopus have?", ["One", "Two", "Three", "Four"], "C", "An octopus has three hearts: two for the gills and one for the body.", "medium"),
        ("Which animal has fingerprints remarkably similar to humans?", ["Koala", "Dog", "Horse", "Rabbit"], "A", "Koalas have fingerprints that are very similar to human ones.", "medium"),
    ],
    "Trick Questions": [
        ("How many months of the year have at least 28 days?", ["1", "2", "11", "12"], "D", "Every month has at least 28 days, so the answer is all 12.", "medium"),
        ("Which is heavier: a kilogram of feathers or a kilogram of steel?", ["Feathers", "Steel", "They weigh the same", "Cannot be determined"], "C", "Both weigh one kilogram.", "easy"),
    ],
}
