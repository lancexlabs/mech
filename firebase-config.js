// firebase-config.js
// ============================================
// 🔥 FIREBASE CONFIGURATION
// Replace these values with your own Firebase project details
// ============================================

export const firebaseConfig = {
    // Get these from your Firebase Console
    // Go to: https://console.firebase.google.com/
    // Select your project → Project Settings → General → Your apps
    
  apiKey: "AIzaSyCLT2q9eTZMnmoxOoKAjJ2hhEbY5cqKZQI",
    authDomain: "mechshop-d84f0.firebaseapp.com",
    projectId: "mechshop-d84f0",
    storageBucket: "mechshop-d84f0.firebasestorage.app",
    messagingSenderId: "351961097826",
    appId: "1:351961097826:web:75de4b8ff69185ad55533b",
    measurementId: "G-ZRKK81HSY5"
};

// ============================================
// 📦 SUPABASE CONFIGURATION (Alternative)
// If using Supabase instead of Firebase
// ============================================

export const supabaseConfig = {
    supabaseUrl: "https://dorfhpebjaslpbqaztnr.supabase.co",
    supabaseAnonKey: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRvcmZocGViamFzbHBicWF6dG5yIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ1MDc1MTEsImV4cCI6MjA5MDA4MzUxMX0.IKEoQ7TT65HA1rua2BVAGBWojMn3VkFYrkTfiDiuWQc"
};

// ============================================
// 🚀 WHICH ONE TO USE?
// ============================================
// This project uses FIREBASE by default.
// If you want to use Supabase, you'll need to modify the imports.