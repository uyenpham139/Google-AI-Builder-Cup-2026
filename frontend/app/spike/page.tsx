'use client';

import { useState } from 'react';

export default function AudioSpikePage() {
  const [isRecording, setIsRecording] = useState(false);

  const startRecording = () => {
    setIsRecording(true);
    // TODO: Implement Web Audio API capture and WebSocket streaming to FastAPI backend
    console.log("Started recording (scaffolding)");
  };

  const stopRecording = () => {
    setIsRecording(false);
    // TODO: Stop Web Audio API capture and close WebSocket
    console.log("Stopped recording (scaffolding)");
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 text-gray-900 p-4">
      <h1 className="text-3xl font-bold mb-6">Gemini Live API Audio Streaming Spike</h1>
      <p className="mb-8 text-center max-w-lg text-gray-600">
        Đây là giao diện scaffolding cho việc test tính năng stream audio từ Frontend (Next.js) sang Backend (FastAPI).
      </p>
      
      <div className="flex gap-4">
        <button 
          onClick={startRecording}
          disabled={isRecording}
          className={`px-6 py-2 rounded-lg font-semibold text-white transition-colors 
            ${isRecording ? 'bg-gray-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700'}`}
        >
          Start Recording
        </button>
        <button 
          onClick={stopRecording}
          disabled={!isRecording}
          className={`px-6 py-2 rounded-lg font-semibold text-white transition-colors 
            ${!isRecording ? 'bg-gray-400 cursor-not-allowed' : 'bg-red-600 hover:bg-red-700'}`}
        >
          Stop Recording
        </button>
      </div>

      <div className="mt-8 p-4 bg-white shadow rounded-lg w-full max-w-md">
        <h2 className="text-lg font-semibold mb-2">Status</h2>
        <div className="flex items-center gap-2">
          <div className={`w-3 h-3 rounded-full ${isRecording ? 'bg-red-500 animate-pulse' : 'bg-gray-300'}`}></div>
          <span>{isRecording ? 'Recording and Streaming...' : 'Idle'}</span>
        </div>
      </div>
    </div>
  );
}
