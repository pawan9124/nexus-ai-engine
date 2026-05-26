import { useState, useEffect } from 'react';
import axios from 'axios';
import { UploadCloud, MessageSquare, Send, Loader2, PlusCircle, MessageCircle, LogOut } from 'lucide-react';

function App() {
  const [file, setFile] = useState(null);
  const [uploadStatus, setUploadStatus] = useState('');

  const [question, setQuestion] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isFetchingHistory, setIsFetchingHistory] = useState(false);

  //tokens and authentications
  const [token, setToken] = useState(localStorage.getItem('token') || null);
  const [username, setUsername] = useState(localStorage.getItem('username') || null);
  const [authMode, setAuthMode] = useState('login');
  const [authForm, setAuthForm] = useState({ username: '', password: '' });
  const [authError, setAuthError] = useState('');



  // New Sidebar State
  const [pastSessions, setPastSessions] = useState([]);

  // We extract the ID generation so we can call it when hitting "New Chat"
  const generateNewId = () => 'chat_' + Math.random().toString(36).substring(2, 9);
  const [sessionId, setSessionId] = useState(generateNewId());

  const API_GATEWAY = "https://nexus-ai-engine-24tb.onrender.com/api/documents";

  // --- SILENT WARM-UP PING ---
  useEffect(() => {
    // We don't await this, and we don't care about the response.
    // We just want to knock on the server's door.
    axios.get('https://nexus-ai-engine-24tb.onrender.com/api/health')
      .catch((err) => console.log("Server waking up ...."));
  }, [])

  // --- NEW: Fetch all sessions on load ---
  useEffect(() => {
    fetchAllSessions();
  }, []);

  const fetchAllSessions = async () => {
    try {
      const res = await axios.get(`${API_GATEWAY}/sessions`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      });
      setPastSessions(res.data.sessions || []);
    } catch (error) {
      console.error("Failed to fetch sessions", error);
    }
  };

  // --- NEW: Load a specific old chat ---
  const loadSession = async (id) => {
    setSessionId(id);
    setChatHistory([]); // Clear screen while loading
    setIsFetchingHistory(true);
    try {
      const res = await axios.get(`${API_GATEWAY}/history/${id}`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      });
      setChatHistory(res.data.messages);
    } catch (error) {
      console.error("Failed to load history", error);
    } finally {
      setIsFetchingHistory(false);
    }
  };

  // --- NEW: Start a fresh chat ---
  const startNewChat = () => {
    setSessionId(generateNewId());
    setChatHistory([]);
  };

  // --- EXISTING LOGIC ---
  const handleFileUpload = async (e) => {
    const selectedFile = e.target.files[0];
    if (!selectedFile) return;
    setFile(selectedFile);
    setUploadStatus('Uploading and vectorizing...');

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('sessionId', sessionId);

    try {
      const response = await axios.post(`${API_GATEWAY}/upload`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
          Authorization: `Bearer ${token}`
        }
      });
      setUploadStatus(`Success: ${response.data.message}`);
    } catch (error) {
      setUploadStatus('Error uploading file. Check console.');
    }
  };

  const handleAskQuestion = async (e) => {
    e.preventDefault();
    if (!question.trim()) return;

    const userMessage = { type: 'user', text: question };
    const emptyAiMessage = { type: 'ai', text: '' };

    setChatHistory((prev) => [...prev, userMessage, emptyAiMessage]);
    setQuestion('');
    setIsLoading(true);

    try {
      const response = await fetch(`${API_GATEWAY}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ question: userMessage.text, sessionId: sessionId })
      });

      if (!response.body) throw new Error("No response body");

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let done = false;
      let accumulatedText = "";

      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        if (value) {
          accumulatedText += decoder.decode(value, { stream: true });
          setChatHistory((prev) => {
            const newHistory = [...prev];
            newHistory[newHistory.length - 1] = { type: 'ai', text: accumulatedText };
            return newHistory;
          });
        }
      }
      // Refresh the sidebar so the new session appears if it was the first question
      fetchAllSessions();
    } catch (error) {
      console.error(error);
    } finally {
      setIsLoading(false);
    }
  };

  // handle Authentications
  const handleAuth = async (e) => {
    e.preventDefault();
    setAuthError('');
    const endpoint = authMode === 'login' ? '/api/auth/login' : '/api/auth/register';

    try {
      //Note: The Auth routes are on port 5000 directly. adjust URL if needed
      const res = await axios.post(`https://nexus-ai-engine-24tb.onrender.com${endpoint}`, authForm);
      if (authMode === 'login') {
        const { token, username } = res.data;
        localStorage.setItem('token', token);
        localStorage.setItem("username", username);
        setToken(token);
        setUsername(username);
        fetchAllSessions(); //fetch history once logged in
      } else {
        setAuthMode('login');
        // Let's reuse authError for success message temporarily, or add a new state.
        // It's a bit hacky to use Error state for success, but user will see it.
        setAuthError('Registration successful. Please login');
      }
    } catch (error) {
      setAuthError(error.response?.data?.error || 'Authentication failed');
    }
  }

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('username');
    setToken(null);
    setUsername('');
    setChatHistory([]);
    setPastSessions([]);
  }

  // IF NOT LOGGED IN, SHOW LOGIN SCREEN
  if (!token) {
    return (
      <div className="min-h-screen bg-[#0f111a] flex items-center justify-center p-4 relative overflow-hidden font-sans">
        {/* Background glow effects */}
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-indigo-600/20 blur-[120px] rounded-full pointer-events-none"></div>
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-blue-600/20 blur-[120px] rounded-full pointer-events-none"></div>

        <div className="bg-white/[0.03] backdrop-blur-xl border border-white/10 p-10 rounded-3xl shadow-2xl max-w-md w-full relative z-10 transition-all duration-500">
          <div className="flex justify-center mb-6">
            <div className="p-3 bg-gradient-to-br from-indigo-500 to-blue-600 rounded-2xl shadow-lg">
              <UploadCloud className="w-8 h-8 text-white" />
            </div>
          </div>
          <h2 className="text-3xl font-extrabold text-center text-white mb-2 tracking-tight">
            Nexus <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-blue-400">AI</span>
          </h2>
          <p className="text-center text-slate-400 text-sm mb-8">Enterprise Document Intelligence</p>

          {authError && (
            <div className={`mb-6 text-sm text-center font-medium p-3 rounded-xl backdrop-blur-md border ${authError.includes('successful') ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'}`}>
              {authError}
            </div>
          )}
          <form onSubmit={handleAuth} className="flex flex-col gap-5">
            <div className="relative group">
              <input
                type="text" placeholder="Username" required
                value={authForm.username} onChange={(e) => setAuthForm({ ...authForm, username: e.target.value })}
                className="w-full p-4 bg-white/[0.03] border border-white/10 rounded-xl text-white placeholder-slate-500 focus:bg-white/[0.05] focus:border-indigo-500/50 focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all"
              />
            </div>
            <div className="relative group">
              <input
                type="password" placeholder="Password" required
                value={authForm.password} onChange={(e) => setAuthForm({ ...authForm, password: e.target.value })}
                className="w-full p-4 bg-white/[0.03] border border-white/10 rounded-xl text-white placeholder-slate-500 focus:bg-white/[0.05] focus:border-indigo-500/50 focus:ring-2 focus:ring-indigo-500/20 outline-none transition-all"
              />
            </div>
            <button type="submit" className="mt-2 relative group overflow-hidden bg-white/5 hover:bg-white/10 text-white p-4 rounded-xl font-semibold transition-all duration-300 border border-white/10 hover:border-indigo-500/50">
              <div className="absolute inset-0 w-full h-full bg-gradient-to-r from-indigo-500/20 to-blue-500/20 opacity-0 group-hover:opacity-100 transition-opacity duration-300"></div>
              <span className="relative flex items-center justify-center gap-2">
                {authMode === 'login' ? 'Access Knowledge Base' : 'Initialize Account'}
              </span>
            </button>
          </form>
          <button
            onClick={() => { setAuthMode(authMode === 'login' ? 'register' : 'login'); setAuthError(''); }}
            className="w-full text-sm text-slate-400 hover:text-indigo-400 mt-6 text-center transition-colors"
          >
            {authMode === 'login' ? "New operative? Request access." : "Already authorized? Proceed to login."}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-[#0f111a] text-slate-200 flex overflow-hidden font-sans selection:bg-indigo-500/30">

      {/* Background ambient light */}
      <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-indigo-600/5 blur-[150px] rounded-full pointer-events-none"></div>

      {/* LEFT SIDEBAR: History */}
      <div className="w-72 bg-[#151822] border-r border-white/5 flex flex-col relative z-10">
        <div className="p-6 flex items-center gap-3">
          <div className="p-2 bg-gradient-to-br from-indigo-500 to-blue-600 rounded-lg shadow-lg shadow-indigo-500/20">
            <UploadCloud className="w-5 h-5 text-white" />
          </div>
          <h1 className="font-bold text-xl tracking-tight text-white">Nexus <span className="text-indigo-400">AI</span></h1>
        </div>

        <div className="px-4 mb-6">
          <button
            onClick={startNewChat}
            className="w-full p-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/20 flex items-center justify-center gap-2 transition-all font-medium text-sm border border-indigo-500/50 hover:border-indigo-400"
          >
            <PlusCircle className="w-4 h-4" /> Start New Session
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-3 pb-4 flex flex-col gap-1 custom-scrollbar">
          <p className="px-3 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider">Session Archives</p>
          {pastSessions.map((id) => (
            <button
              key={id}
              onClick={() => loadSession(id)}
              className={`p-3 text-left rounded-xl text-sm flex items-center gap-3 truncate transition-all duration-200 border ${sessionId === id ? 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20 shadow-sm' : 'border-transparent text-slate-400 hover:bg-white/5 hover:text-slate-200'}`}
            >
              <MessageCircle className={`w-4 h-4 shrink-0 ${sessionId === id ? 'text-indigo-400' : 'text-slate-500'}`} />
              {id}
            </button>
          ))}
        </div>

        <div className="p-4 border-t border-white/5 bg-[#151822] mt-auto">
          <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/5">
            <div className="flex items-center gap-3 truncate">
              <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-500 to-purple-500 flex items-center justify-center text-white font-bold text-sm shadow-inner">
                {username?.charAt(0).toUpperCase()}
              </div>
              <span className="text-sm font-medium truncate text-slate-300">{username}</span>
            </div>
            <button onClick={handleLogout} className="text-slate-500 hover:text-red-400 transition-colors p-2 rounded-lg hover:bg-red-500/10" title="Sign Out">
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* CENTER: Main Area */}
      <div className="flex-1 flex flex-col relative z-10 max-w-5xl mx-auto w-full h-full p-6 gap-6">

        {/* Top: Upload Area & Header */}
        <div className="bg-white/5 backdrop-blur-md border border-white/10 rounded-2xl p-5 flex items-center justify-between shadow-xl">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              Intelligence Core
            </h2>
            <p className="text-sm text-slate-400">Upload documents to expand knowledge base.</p>
          </div>
          <div className="flex items-center gap-4">
            {uploadStatus && (
              <span className="text-xs font-medium text-emerald-400 bg-emerald-500/10 px-3 py-1.5 rounded-full border border-emerald-500/20">
                {uploadStatus}
              </span>
            )}
            <label className="cursor-pointer group flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl transition-all text-sm font-medium text-slate-300 hover:text-white">
              <UploadCloud className="w-4 h-4 text-indigo-400 group-hover:text-indigo-300 transition-colors" />
              Upload Document
              <input
                type="file"
                accept=".pdf"
                onChange={handleFileUpload}
                className="hidden"
              />
            </label>
          </div>
        </div>

        {/* Bottom: Chat Interface */}
        <div className="flex-1 bg-[#151822]/80 backdrop-blur-xl rounded-2xl border border-white/5 flex flex-col overflow-hidden shadow-2xl shadow-black/50">
          <div className="px-6 py-4 border-b border-white/5 bg-white/[0.02]">
            <h2 className="text-sm font-medium text-slate-300 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-indigo-500 shadow-[0_0_8px_rgba(99,102,241,0.8)]"></span>
              Active Session <span className="text-slate-500 font-mono text-xs ml-2">{sessionId}</span>
            </h2>
          </div>

          <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-6 custom-scrollbar">
            {isFetchingHistory ? (
              <div className="h-full flex flex-col items-center justify-center text-slate-400 gap-4">
                <Loader2 className="animate-spin w-10 h-10 text-indigo-500" />
                <p className="text-sm animate-pulse font-medium">Waiting to load the chat...</p>
              </div>
            ) : chatHistory.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-slate-500 gap-4">
                <div className="p-4 rounded-full bg-white/5 border border-white/10">
                  <MessageSquare className="w-8 h-8 text-indigo-400/50" />
                </div>
                <p className="text-sm">Initiate a query to begin processing.</p>
              </div>
            ) : (
              chatHistory.map((msg, index) => (
                <div key={index} className={`flex w-full ${msg.type === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[80%] p-4 text-[15px] leading-relaxed ${msg.type === 'user'
                    ? 'bg-indigo-600 text-white rounded-2xl rounded-tr-sm shadow-md'
                    : 'bg-white/5 text-slate-200 rounded-2xl rounded-tl-sm border border-white/5'
                    }`}>
                    {msg.text}
                  </div>
                </div>
              ))
            )}
            {isLoading && (
              <div className="flex w-full justify-start">
                <div className="bg-white/5 border border-white/5 rounded-2xl rounded-tl-sm p-4 text-slate-400 flex items-center gap-3">
                  <Loader2 className="animate-spin w-4 h-4 text-indigo-400" />
                  <span className="text-sm">Synthesizing response...</span>
                </div>
              </div>
            )}
          </div>

          <form onSubmit={handleAskQuestion} className="p-4 bg-white/[0.02] border-t border-white/5">
            <div className="relative flex items-center">
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Query the document database..."
                className="flex-1 bg-[#0f111a] border border-white/10 rounded-xl py-4 pl-4 pr-16 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/50 transition-all text-[15px]"
                disabled={isLoading}
              />
              <button
                type="submit"
                disabled={isLoading || !question.trim()}
                className="absolute right-2 p-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-white/5 disabled:text-slate-600 text-white rounded-lg transition-colors flex items-center justify-center disabled:cursor-not-allowed"
              >
                <Send className="w-5 h-5" />
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* Global CSS for custom scrollbar hidden in Tailwind */}
      <style dangerouslySetInnerHTML={{
        __html: `
        .custom-scrollbar::-webkit-scrollbar {
          width: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background-color: rgba(255, 255, 255, 0.1);
          border-radius: 10px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background-color: rgba(255, 255, 255, 0.2);
        }
      `}} />
    </div>
  );
}

export default App;