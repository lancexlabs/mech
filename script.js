// script.js
// ============================================
// MECHANIC SHOP MANAGEMENT SYSTEM
// Complete Firebase Integration
// ============================================

import { initializeApp } from "https://www.gstatic.com/firebasejs/9.22.2/firebase-app.js";
import { 
    getFirestore, 
    collection, 
    addDoc, 
    getDocs, 
    getDoc,
    query, 
    where, 
    doc, 
    updateDoc, 
    deleteDoc,
    onSnapshot, 
    serverTimestamp,
    orderBy,
    limit
} from "https://www.gstatic.com/firebasejs/9.22.2/firebase-firestore.js";
import { 
    getStorage, 
    ref, 
    uploadBytes, 
    getDownloadURL, 
    deleteObject 
} from "https://www.gstatic.com/firebasejs/9.22.2/firebase-storage.js";
import { 
    getAuth, 
    signInWithPopup, 
    GoogleAuthProvider, 
    signOut,
    onAuthStateChanged
} from "https://www.gstatic.com/firebasejs/9.22.2/firebase-auth.js";

// ============================================
// 🔥 FIREBASE CONFIGURATION
// REPLACE THESE WITH YOUR OWN FIREBASE CREDENTIALS
// ============================================

const firebaseConfig = {
    // 🔴 IMPORTANT: Replace these with your actual Firebase project details
    // Get them from: https://console.firebase.google.com/
    
    apiKey: "AIzaSyCLT2q9eTZMnmoxOoKAjJ2hhEbY5cqKZQI",
    authDomain: "mechshop-d84f0.firebaseapp.com",
    projectId: "mechshop-d84f0",
    storageBucket: "mechshop-d84f0.firebasestorage.app",
    messagingSenderId: "351961097826",
    appId: "1:351961097826:web:75de4b8ff69185ad55533b",
    measurementId: "G-ZRKK81HSY5"
};

// ============================================
// 🚀 INITIALIZE FIREBASE
// ============================================

// Initialize Firebase
const app = initializeApp(firebaseConfig);

// Initialize Firestore (Database)
const db = getFirestore(app);

// Initialize Storage (For images)
const storage = getStorage(app);

// Initialize Authentication
const auth = getAuth(app);

// Google Auth Provider
const googleProvider = new GoogleAuthProvider();

// ============================================
// 📝 HELPER FUNCTIONS
// ============================================

// Status steps for tracking
export const statusSteps = [
    "Pending",
    "Pickup Scheduled", 
    "On the Way",
    "Picked",
    "In Progress",
    "Waiting Parts",
    "Quotation Sent",
    "Quotation Rejected",
    "Completed"
];

// ============================================
// 🔧 CORE DATABASE FUNCTIONS
// ============================================

/**
 * Add a new booking to Firestore
 * @param {Object} bookingData - Customer booking information
 * @returns {Promise<string>} - Booking ID
 */
export async function addBooking(bookingData) {
    try {
        const docRef = await addDoc(collection(db, "bookings"), {
            ...bookingData,
            status: "Pending",
            quotation: null,
            quotationDetails: null,
            quotationAccepted: null,
            finalImageUrl: null,
            createdAt: serverTimestamp(),
            updatedAt: serverTimestamp()
        });
        console.log("✅ Booking added with ID:", docRef.id);
        return docRef.id;
    } catch (error) {
        console.error("❌ Error adding booking:", error);
        throw error;
    }
}

/**
 * Get booking by ID or phone number
 * @param {string} key - Booking ID or phone number
 * @returns {Promise<Object|null>} - Booking data or null
 */
export async function getBookingByKey(key) {
    try {
        // First try as document ID
        const docSnap = await getDoc(doc(db, "bookings", key));
        if (docSnap.exists()) {
            return { id: docSnap.id, ...docSnap.data() };
        }
        
        // If not found, search by phone number
        const q = query(collection(db, "bookings"), where("phone", "==", key));
        const querySnapshot = await getDocs(q);
        
        if (!querySnapshot.empty) {
            const docData = querySnapshot.docs[0];
            return { id: docData.id, ...docData.data() };
        }
        
        return null;
    } catch (error) {
        console.error("❌ Error getting booking:", error);
        return null;
    }
}

/**
 * Get all bookings with real-time updates
 * @param {Function} callback - Function to handle updates
 * @returns {Function} - Unsubscribe function
 */
export function onBookingsUpdate(callback) {
    const q = query(collection(db, "bookings"), orderBy("createdAt", "desc"));
    return onSnapshot(q, (snapshot) => {
        const bookings = [];
        snapshot.forEach(doc => {
            bookings.push({ id: doc.id, ...doc.data() });
        });
        callback(bookings);
    }, (error) => {
        console.error("❌ Error in real-time updates:", error);
    });
}

/**
 * Update booking status
 * @param {string} bookingId - Booking document ID
 * @param {string} newStatus - New status value
 */
export async function updateBookingStatus(bookingId, newStatus) {
    try {
        await updateDoc(doc(db, "bookings", bookingId), {
            status: newStatus,
            updatedAt: serverTimestamp()
        });
        console.log("✅ Status updated to:", newStatus);
    } catch (error) {
        console.error("❌ Error updating status:", error);
        throw error;
    }
}

/**
 * Send quotation to customer
 * @param {string} bookingId - Booking document ID
 * @param {Object} quotationData - Quotation details
 */
export async function sendQuotation(bookingId, quotationData) {
    try {
        await updateDoc(doc(db, "bookings", bookingId), {
            quotation: quotationData.total,
            quotationDetails: quotationData,
            status: "Quotation Sent",
            quotationAccepted: null,
            updatedAt: serverTimestamp()
        });
        console.log("✅ Quotation sent:", quotationData);
    } catch (error) {
        console.error("❌ Error sending quotation:", error);
        throw error;
    }
}

/**
 * Update customer's response to quotation
 * @param {string} bookingId - Booking document ID
 * @param {boolean} accepted - Whether quotation was accepted
 */
export async function updateQuotationResponse(bookingId, accepted) {
    try {
        await updateDoc(doc(db, "bookings", bookingId), {
            quotationAccepted: accepted,
            status: accepted ? "In Progress" : "Quotation Rejected",
            updatedAt: serverTimestamp()
        });
        console.log("✅ Quotation response:", accepted ? "Accepted" : "Rejected");
    } catch (error) {
        console.error("❌ Error updating response:", error);
        throw error;
    }
}

/**
 * Upload final vehicle image to Storage
 * @param {string} bookingId - Booking document ID
 * @param {File} file - Image file to upload
 * @returns {Promise<string>} - Download URL of uploaded image
 */
export async function uploadFinalImage(bookingId, file) {
    try {
        // Create a unique filename
        const timestamp = Date.now();
        const filename = `${timestamp}_${file.name}`;
        const storageRef = ref(storage, `final_images/${bookingId}/${filename}`);
        
        // Upload file
        const snapshot = await uploadBytes(storageRef, file);
        console.log("✅ File uploaded successfully");
        
        // Get download URL
        const downloadUrl = await getDownloadURL(snapshot.ref);
        
        // Update Firestore with image URL
        await updateDoc(doc(db, "bookings", bookingId), {
            finalImageUrl: downloadUrl,
            status: "Completed",
            updatedAt: serverTimestamp()
        });
        
        console.log("✅ Image URL saved to database");
        return downloadUrl;
    } catch (error) {
        console.error("❌ Error uploading image:", error);
        throw error;
    }
}

/**
 * Delete booking (Admin only)
 * @param {string} bookingId - Booking document ID
 */
export async function deleteBooking(bookingId) {
    try {
        await deleteDoc(doc(db, "bookings", bookingId));
        console.log("✅ Booking deleted:", bookingId);
    } catch (error) {
        console.error("❌ Error deleting booking:", error);
        throw error;
    }
}

/**
 * Get bookings by status
 * @param {string} status - Status to filter by
 * @returns {Promise<Array>} - Array of bookings
 */
export async function getBookingsByStatus(status) {
    try {
        const q = query(collection(db, "bookings"), where("status", "==", status));
        const querySnapshot = await getDocs(q);
        const bookings = [];
        querySnapshot.forEach(doc => {
            bookings.push({ id: doc.id, ...doc.data() });
        });
        return bookings;
    } catch (error) {
        console.error("❌ Error getting bookings by status:", error);
        return [];
    }
}

// ============================================
// 🔐 AUTHENTICATION FUNCTIONS
// ============================================

/**
 * Sign in with Google
 */
export async function signInWithGoogle() {
    try {
        const result = await signInWithPopup(auth, googleProvider);
        console.log("✅ Signed in:", result.user.email);
        return result.user;
    } catch (error) {
        console.error("❌ Google sign-in error:", error);
        throw error;
    }
}

/**
 * Sign out user
 */
export async function signOutUser() {
    try {
        await signOut(auth);
        console.log("✅ User signed out");
    } catch (error) {
        console.error("❌ Sign out error:", error);
        throw error;
    }
}

/**
 * Check if user is admin
 * @param {string} email - User email
 * @returns {boolean} - True if admin
 */
export function isAdmin(email) {
    // Add your admin emails here
    const adminEmails = [
        "admin@example.com",
        "mechanic@quickfix.com",
        "your-email@gmail.com"  // ← Add your email here
    ];
    return adminEmails.includes(email);
}

/**
 * Get current authenticated user
 * @param {Function} callback - Callback with user data
 */
export function onAuthState(callback) {
    return onAuthStateChanged(auth, (user) => {
        callback(user);
    });
}

// ============================================
// 🎨 UI HELPER FUNCTIONS
// ============================================

/**
 * Setup service type toggle (Self Drop / Pickup)
 */
export function setupServiceTypeToggle() {
    const serviceType = document.getElementById('serviceType');
    const pickupFields = document.getElementById('pickupFields');
    
    if (serviceType && pickupFields) {
        serviceType.addEventListener('change', () => {
            if (serviceType.value === 'Pickup') {
                pickupFields.classList.add('show');
                document.getElementById('pickupAddress').required = true;
                document.getElementById('pickupTime').required = true;
            } else {
                pickupFields.classList.remove('show');
                document.getElementById('pickupAddress').required = false;
                document.getElementById('pickupTime').required = false;
            }
        });
    }
}

// ============================================
// 📊 STATISTICS FUNCTIONS
// ============================================

/**
 * Get booking statistics
 * @returns {Promise<Object>} - Statistics object
 */
export async function getBookingStats() {
    try {
        const allBookings = [];
        const snapshot = await getDocs(collection(db, "bookings"));
        snapshot.forEach(doc => allBookings.push(doc.data()));
        
        return {
            total: allBookings.length,
            pending: allBookings.filter(b => b.status === "Pending").length,
            inProgress: allBookings.filter(b => ["In Progress", "Quotation Sent", "Pickup Scheduled"].includes(b.status)).length,
            completed: allBookings.filter(b => b.status === "Completed").length,
            rejected: allBookings.filter(b => b.status === "Quotation Rejected").length
        };
    } catch (error) {
        console.error("❌ Error getting stats:", error);
        return { total: 0, pending: 0, inProgress: 0, completed: 0, rejected: 0 };
    }
}

// ============================================
// 🧹 EXPORT ALL FUNCTIONS
// ============================================

export {
    db,
    storage,
    auth,
    addDoc,
    collection,
    getDocs,
    updateDoc,
    deleteDoc,
    onSnapshot,
    serverTimestamp
};

console.log("🚀 Firebase initialized successfully!");