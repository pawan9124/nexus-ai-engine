require('dotenv').config()
const express = require("express")
const cors = require('cors')
const multer = require('multer')
const axios = require('axios')
const FormData = require("form-data")

// == NEW SECURITY IMPORTS ===
const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');
const { MongoClient } = require("mongodb");


const app = express()
const PORT = 5000

// The internal URL of your Python AI Microservice
const PYTHON_AI_URL = process.env.PYTHON_AI_URL;

//  --- MIDDLEWARE ----
app.use(cors());
app.use(express.json());

//Configure Multer o hold the uploaded file in RAM (memory storage)
//This prvents us from having to save teh file to disk twice
const upload = multer({ storage: multer.memoryStorage() });


// --- MONGODB CONNECTION FOR NODE ---
let db;
MongoClient.connect(process.env.MONGO_URI)
    .then(client => {
        db = client.db('enterprise_rag');
        console.log(" Node Gateway connected to MongoDB");
    }).catch(error => {
        console.error(" MongoDB Connection Error:", error)
    })

// =================================================
// ---- SECURITY MIDDLEWARES -------------------
// ================================================

const authenticationToken = (req, res, next) => {
    // 1. Look for the token in the headers
    const authHeader = req.headers['authorization'];
    const token = authHeader && authHeader.split(' ')[1]; //Format: "Bearer <token>"

    // 2. If no token, kick them out
    if (!token) return res.status(401).json({ error: "Access Denied. No token provided." })

    // 3. Verify the token against your secret key
    jwt.verify(token, process.env.JWT_SECRET, (err, user) => {
        if (err) return res.status(403).json({ error: "Invalid or expired Token" });

        // 4. Attach the decoded user data to the request so downstream routes can use it
        req.user = user;
        next(); //Let them pass !
    })
}
//  ---- ROUTES ---

// ==================================
// --- NEW AUTHENTICATION ROUTES ---
// ==================================

app.post("/api/auth/register", async (req, res) => {
    try {
        const { username, password } = req.body;
        if (!username || !password) return res.status(400).json({ error: "Missing username or password" })

        //check if the user exists already
        const existingUser = await db.collection('users').findOne({ username });
        if (existingUser) return res.status(400).json({ error: "User already exists." })

        //Hash Password and save it
        const hashPassword = await bcrypt.hash(password, 10);
        const newUser = { username, password: hashPassword, createdAt: new Date() };
        await db.collection('users').insertOne(newUser);

        res.json({ message: "User registered successfully!" })
    } catch (error) {
        res.status(500).json({ error: 'Server Error' })
    }
})


//login api route
app.post("/api/auth/login", async (req, res) => {
    try {
        const { username, password } = req.body;

        //Find the user
        const user = await db.collection('users').findOne({ username });
        if (!user) return res.status(400).json({ error: "Invalid Credentials" })

        //check password 
        const isMatch = await bcrypt.compare(password, user.password);
        if (!isMatch) return res.status(400).json({ error: "Invalid Credentials" });

        //Generate JWT
        const token = jwt.sign({ userId: user._id, username: username }, process.env.JWT_SECRET, { expiresIn: '24h' });

        res.json({ token, username: user.username });
    } catch (error) {
        res.status(500).json({ error: "Login Error", err: error.message })
    }
})

// 1. Health Check Route
app.get("/api/health", (req, res) => {
    res.json({ status: "Gateway is running", ai_service: 'checking....' })
});

// 2. THE PDF upload proxy
app.post('/api/documents/upload', authenticationToken, upload.single('file'), async (req, res) => {
    try {
        if (!req.file) {
            return res.status(400).json({ error: "No PDF file provided" });
        }

        // Grab the session Id from the React FormData
        const { sessionId } = req.body;

        console.log(`[Gateway] Received file:${req.file.originalname}. Forwarding to AI Brain....`)

        // Create a fake form submission to send to the Python
        const formData = new FormData();
        //We pass the buffer (the raw file data in RAM)  and the original filename
        formData.append("file", req.file.buffer, req.file.originalname);

        // Forward the sessionId to Python
        formData.append('session_id', sessionId || 'default_session');


        // Forward the request to the Python microservice
        const pythonResponse = await axios.post(
            `${PYTHON_AI_URL}/api/upload`,
            formData,
            {
                headers: {
                    ...formData.getHeaders(),
                    Authorization: req.headers.authorization
                }
            }
        )

        //Send Python's success message back to the frontend
        res.json(pythonResponse.data)

    } catch (error) {
        console.error("[Gateway Error]", error.message)
        res.status(500).json({ error: "Failed to process document in AI microservices" })
    }
});

//3. The RAG Chat proxy
app.post("/api/documents/chat", authenticationToken, async (req, res) => {
    try {
        console.log("REQU;;;;", req)
        const { question, sessionId } = req.body;

        if (!question) {
            return res.status(400).json({ error: "No question provided." })
        }

        console.log(`[Gateway] Received Question:"${question}". Fowarding to AI Brain....`)

        //Forward the JSON question to the Python microservice
        const pythonResponse = await axios.post(
            `${PYTHON_AI_URL}/api/chat`,
            {
                question: question,
                session_id: sessionId || 'default_session' // fallback just in case of no session id
            },
            {
                responseType: 'stream', //CRITICAL for streaming
                headers: {
                    Authorization: req.headers.authorization
                }
            }
        )
        //Set Headers so the React frontend knows a stream is coming
        res.setHeader('Content-Type', 'text/event-stream');
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');

        //Pipe the Python stream directly into the Node.js respnose
        pythonResponse.data.pipe(res);

    } catch (error) {
        console.log("ERRORO", error)
        console.log(`[Error]: Getting error while chatting ${error.message}`)
        res.status(500).json({ error: "Error while chatting with AI service" })
    }

})

// 4. Get all Session IDs
app.get("/api/documents/sessions", authenticationToken, async (req, res) => {
    try {
        const pythonResponse = await axios.get(`${PYTHON_AI_URL}/api/sessions/`, {
            headers: {
                Authorization: req.headers.authorization
            }
        });
        res.json(pythonResponse.data)
    } catch (error) {
        console.error("[Gateway Error]", error.message);
        res.status(500).json({ error: "Failed to fetch history" })
    }
})

// 5. Get a specific Sessions' history
app.get('/api/documents/history/:sessionId', authenticationToken, async (req, res) => {
    try {
        const pythonResponse = await axios.get(`${PYTHON_AI_URL}/api/history/${req.params.sessionId}`, {
            headers: {
                Authorization: req.headers.authorization
            }
        });
        res.json(pythonResponse.data)
    } catch (error) {
        console.error('[Gateway Error]', error.message);
        res.status(500).json({ error: 'Failed to fetch the history' });
    }
});


//========================================
// ---------- WARM UP PING ROUTE --------
//========================================

app.get("/api/health", async (req, res) => {
    try {
        // Ping Python to wake it up simultaneously
        await axios.get(`${PYTHON_AI_URL}/api/health`);
        res.json({ status: "Gateway and Brain are awake" });
    } catch (error) {
        //Even if Python times out on the first ping, the container is still waking up! 
        res.status(202).json({ status: "Waking up..." })
    }
})


//Start the server
app.listen(PORT, () => {
    console.log(` Node.js API Gateway running on http//localhost: ${PORT}`);
    console.log(` Routing AI requests to ${PYTHON_AI_URL}`)
})