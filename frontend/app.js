

const API_BASE = "http://localhost:5000/api";

const { createApp } = Vue;

createApp({
  data() {
    return {
      // --- session ---
      token: localStorage.getItem("tma_token") || null,
      currentUser: JSON.parse(localStorage.getItem("tma_user") || "null"),

      // top-level view routing: browse | login | register | dashboard 
      view: "browse",
      dashboardTab: "overview",

      // UI feedback
      loading: false,
      errorMsg: "",
      successMsg: "",

      // public trek browsing
      treks: [],
      searchQuery: "",
      locationFilter: "",
      difficultyFilter: "",

      // --- auth forms ---
      loginForm: { email: "", password: "" },
      registerForm: { name: "", email: "", password: "", confirmPassword: "", phone: "" },

      // --- booking modal ---
      bookingModalTrek: null,
      bookingSlots: 1,

      // --- trekker dashboard ---
      myBookings: [],
      exportTaskId: null,
      exportPolling: false,
      exportResult: null,

      // --- staff dashboard ---
      myTreks: [],
      trekForm: this.blankTrekForm(),
      editingTrekId: null,
      bookingsModalTrek: null,
      bookingsModalList: [],

      // --- admin dashboard ---
      dashboardStats: null,
      pendingTreks: [],
      allUsers: [],
      userRoleFilter: "",
      allTreksAdmin: [],
      adminTrekStatusFilter: "",
      staffForm: {
        name: "", email: "", password: "", phone: "", designation: "Trek Coordinator", assigned_region: "",
      },
      reportTaskId: null,
      reportPolling: false,
      reportResult: null,
      reminderTaskId: null,
      reminderPolling: false,
      reminderResult: null,
    };
  },

  computed: {
    isLoggedIn() {
      return !!this.token;
    },
    role() {
      return this.currentUser ? this.currentUser.role : null;
    },
  },

  mounted() {
    this.fetchTreks();
    if (this.isLoggedIn) {
      this.view = "dashboard";
      this.loadDashboardForRole();
    }
  },

  methods: {
    // =======================================================================
    // Generic helpers
    // =======================================================================
    blankTrekForm() {
      return {
        title: "", description: "", location: "", difficulty: "moderate",
        start_date: "", end_date: "", total_slots: 10, price: 0,
      };
    },

    flash(message, type = "success") {
      if (type === "success") {
        this.successMsg = message;
        this.errorMsg = "";
      } else {
        this.errorMsg = message;
        this.successMsg = "";
      }
      setTimeout(() => {
        this.successMsg = "";
        this.errorMsg = "";
      }, 5000);
    },

    async apiRequest(method, endpoint, body = null, auth = true) {
      const headers = { "Content-Type": "application/json" };
      if (auth && this.token) headers["Authorization"] = `Bearer ${this.token}`;

      const options = { method, headers };
      if (body !== null) options.body = JSON.stringify(body);

      let response;
      try {
        response = await fetch(`${API_BASE}${endpoint}`, options);
      } catch (networkErr) {
        throw new Error(
          "Could not reach the API server. Is the Flask backend running on http://localhost:5000?"
        );
      }

      let data = {};
      try {
        data = await response.json();
      } catch (parseErr) {
        data = {};
      }

      if (!response.ok) {
        throw new Error(data.error || `Request failed (HTTP ${response.status})`);
      }
      return data;
    },

    formatDate(isoStr) {
      if (!isoStr) return "-";
      const d = new Date(isoStr);
      return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
    },

    formatMoney(amount) {
      return `₹${Number(amount || 0).toFixed(2)}`;
    },

    statusBadgeClass(status) {
      const map = {
        pending: "text-bg-warning",
        approved: "text-bg-info",
        open: "text-bg-success",
        closed: "text-bg-secondary",
        completed: "text-bg-dark",
        rejected: "text-bg-danger",
        confirmed: "text-bg-success",
        cancelled: "text-bg-secondary",
        active: "text-bg-success",
        blacklisted: "text-bg-danger",
      };
      return map[status] || "text-bg-light";
    },

    // =======================================================================
    // Navigation
    // =======================================================================
    goTo(view) {
      this.view = view;
      this.errorMsg = "";
      this.successMsg = "";
      if (view === "browse") this.fetchTreks();
    },

    loadDashboardForRole() {
      if (this.role === "admin") {
        this.dashboardTab = "overview";
        this.fetchDashboardStats();
        this.fetchPendingTreks();
      } else if (this.role === "staff") {
        this.dashboardTab = "my-treks";
        this.fetchMyTreks();
      } else if (this.role === "trekker") {
        this.dashboardTab = "my-bookings";
        this.fetchMyBookings();
      }
    },

    switchDashboardTab(tab) {
      this.dashboardTab = tab;
      this.errorMsg = "";
      this.successMsg = "";
      if (tab === "overview") this.fetchDashboardStats();
      if (tab === "pending-approvals") this.fetchPendingTreks();
      if (tab === "manage-users") this.fetchAllUsers();
      if (tab === "all-treks") this.fetchAllTreksAdmin();
      if (tab === "my-treks") this.fetchMyTreks();
      if (tab === "my-bookings") this.fetchMyBookings();
    },

    // =======================================================================
    // Auth
    // =======================================================================
    async submitLogin() {
      if (!this.loginForm.email || !this.loginForm.password) {
        this.flash("Please enter both email and password", "error");
        return;
      }
      this.loading = true;
      try {
        const data = await this.apiRequest("POST", "/auth/login", this.loginForm, false);
        this.token = data.token;
        this.currentUser = data.user;
        localStorage.setItem("tma_token", this.token);
        localStorage.setItem("tma_user", JSON.stringify(this.currentUser));
        this.loginForm = { email: "", password: "" };
        this.flash(`Welcome back, ${this.currentUser.name}!`);
        this.view = "dashboard";
        this.loadDashboardForRole();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async submitRegister() {
      const f = this.registerForm;
      if (!f.name || !f.email || !f.password) {
        this.flash("Name, email and password are required", "error");
        return;
      }
      if (f.password.length < 6) {
        this.flash("Password must be at least 6 characters", "error");
        return;
      }
      if (f.password !== f.confirmPassword) {
        this.flash("Passwords do not match", "error");
        return;
      }
      this.loading = true;
      try {
        const data = await this.apiRequest("POST", "/auth/register", {
          name: f.name, email: f.email, password: f.password, phone: f.phone,
        }, false);
        this.token = data.token;
        this.currentUser = data.user;
        localStorage.setItem("tma_token", this.token);
        localStorage.setItem("tma_user", JSON.stringify(this.currentUser));
        this.registerForm = { name: "", email: "", password: "", confirmPassword: "", phone: "" };
        this.flash(`Account created! Welcome, ${this.currentUser.name}.`);
        this.view = "dashboard";
        this.loadDashboardForRole();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    logout() {
      this.token = null;
      this.currentUser = null;
      localStorage.removeItem("tma_token");
      localStorage.removeItem("tma_user");
      this.view = "browse";
      this.fetchTreks();
      this.flash("You have been logged out");
    },

    // =======================================================================
    // Public: browse / search treks
    // =======================================================================
    async fetchTreks() {
      this.loading = true;
      try {
        const params = new URLSearchParams();
        if (this.searchQuery) params.set("search", this.searchQuery);
        if (this.locationFilter) params.set("location", this.locationFilter);
        if (this.difficultyFilter) params.set("difficulty", this.difficultyFilter);
        const qs = params.toString() ? `?${params.toString()}` : "";
        const data = await this.apiRequest("GET", `/treks${qs}`, null, false);
        this.treks = data.treks;
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    resetFilters() {
      this.searchQuery = "";
      this.locationFilter = "";
      this.difficultyFilter = "";
      this.fetchTreks();
    },

    // =======================================================================
    // Trekker: booking flow
    // =======================================================================
    openBookingModal(trek) {
      if (!this.isLoggedIn) {
        this.flash("Please log in as a trekker to book a trek", "error");
        this.view = "login";
        return;
      }
      if (this.role !== "trekker") {
        this.flash("Only trekker accounts can book treks", "error");
        return;
      }
      this.bookingModalTrek = trek;
      this.bookingSlots = 1;
    },

    closeBookingModal() {
      this.bookingModalTrek = null;
      this.bookingSlots = 1;
    },

    async confirmBooking() {
      if (!this.bookingModalTrek) return;
      const slots = parseInt(this.bookingSlots, 10);
      if (!slots || slots < 1) {
        this.flash("Please enter a valid number of slots", "error");
        return;
      }
      if (slots > this.bookingModalTrek.available_slots) {
        this.flash(`Only ${this.bookingModalTrek.available_slots} slot(s) available`, "error");
        return;
      }
      this.loading = true;
      try {
        await this.apiRequest("POST", `/treks/${this.bookingModalTrek.id}/book`, { num_slots: slots });
        this.flash("Booking confirmed! View it under My Bookings.");
        this.closeBookingModal();
        this.fetchTreks();
        if (this.view === "dashboard") this.fetchMyBookings();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async fetchMyBookings() {
      this.loading = true;
      try {
        const data = await this.apiRequest("GET", "/bookings/my");
        this.myBookings = data.bookings;
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async cancelMyBooking(bookingId) {
      if (!confirm("Cancel this booking?")) return;
      this.loading = true;
      try {
        await this.apiRequest("PUT", `/bookings/${bookingId}/cancel`);
        this.flash("Booking cancelled");
        this.fetchMyBookings();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    // --- async CSV export (user-triggered Celery task) ---
    async startExport() {
      this.exportResult = null;
      this.loading = true;
      try {
        const data = await this.apiRequest("POST", "/bookings/export");
        this.exportTaskId = data.task_id;
        this.flash("Export started - this runs in the background, hang tight...");
        this.pollExportTask();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async pollExportTask() {
      if (!this.exportTaskId) return;
      this.exportPolling = true;
      const poll = async () => {
        try {
          const data = await this.apiRequest("GET", `/tasks/${this.exportTaskId}`);
          if (data.state === "SUCCESS") {
            this.exportResult = data.result;
            this.exportPolling = false;
            this.flash("Export ready - download it below.");
          } else if (data.state === "FAILURE") {
            this.exportPolling = false;
            this.flash(`Export failed: ${data.error || "unknown error"}`, "error");
          } else {
            setTimeout(poll, 1500);
          }
        } catch (err) {
          this.exportPolling = false;
          this.flash(err.message, "error");
        }
      };
      poll();
    },

    downloadExportCsv() {
      if (!this.exportResult || !this.exportResult.csv_content) return;
      const blob = new Blob([this.exportResult.csv_content], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = this.exportResult.export_file || "booking_history.csv";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    },

    // =======================================================================
    // Staff: trek management
    // =======================================================================
    async fetchMyTreks() {
      this.loading = true;
      try {
        const data = await this.apiRequest("GET", "/staff/treks");
        this.myTreks = data.treks;
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    startEditTrek(trek) {
      this.editingTrekId = trek.id;
      this.trekForm = {
        title: trek.title,
        description: trek.description || "",
        location: trek.location,
        difficulty: trek.difficulty,
        start_date: trek.start_date,
        end_date: trek.end_date,
        total_slots: trek.total_slots,
        price: trek.price,
      };
      this.dashboardTab = "create-trek";
    },

    cancelEditTrek() {
      this.editingTrekId = null;
      this.trekForm = this.blankTrekForm();
    },

    validateTrekForm() {
      const f = this.trekForm;
      if (!f.title || !f.location || !f.start_date || !f.end_date) {
        this.flash("Title, location, and both dates are required", "error");
        return false;
      }
      if (new Date(f.end_date) < new Date(f.start_date)) {
        this.flash("End date cannot be before start date", "error");
        return false;
      }
      if (!f.total_slots || f.total_slots < 1) {
        this.flash("Total slots must be at least 1", "error");
        return false;
      }
      if (f.price === "" || f.price < 0) {
        this.flash("Price cannot be negative", "error");
        return false;
      }
      return true;
    },

    async submitTrekForm() {
      if (!this.validateTrekForm()) return;
      this.loading = true;
      try {
        if (this.editingTrekId) {
          await this.apiRequest("PUT", `/staff/treks/${this.editingTrekId}`, this.trekForm);
          this.flash("Trek updated");
        } else {
          await this.apiRequest("POST", "/staff/treks", this.trekForm);
          this.flash("Trek submitted for admin approval");
        }
        this.cancelEditTrek();
        this.dashboardTab = "my-treks";
        this.fetchMyTreks();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async openTrekForBooking(trekId) {
      this.loading = true;
      try {
        await this.apiRequest("PUT", `/staff/treks/${trekId}/open`);
        this.flash("Trek opened for booking");
        this.fetchMyTreks();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async closeTrekBooking(trekId) {
      this.loading = true;
      try {
        await this.apiRequest("PUT", `/staff/treks/${trekId}/close`);
        this.flash("Trek closed for booking");
        this.fetchMyTreks();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async markTrekComplete(trekId) {
      if (!confirm("Mark this trek as completed?")) return;
      this.loading = true;
      try {
        await this.apiRequest("PUT", `/staff/treks/${trekId}/complete`);
        this.flash("Trek marked as completed");
        this.fetchMyTreks();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async viewTrekBookings(trek) {
      this.loading = true;
      try {
        const data = await this.apiRequest("GET", `/staff/treks/${trek.id}/bookings`);
        this.bookingsModalTrek = data.trek;
        this.bookingsModalList = data.bookings;
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    closeBookingsModal() {
      this.bookingsModalTrek = null;
      this.bookingsModalList = [];
    },

    // =======================================================================
    // Admin: dashboard stats
    // =======================================================================
    async fetchDashboardStats() {
      this.loading = true;
      try {
        this.dashboardStats = await this.apiRequest("GET", "/admin/dashboard/stats");
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    // --- trek approvals ---
    async fetchPendingTreks() {
      this.loading = true;
      try {
        const data = await this.apiRequest("GET", "/admin/treks/pending");
        this.pendingTreks = data.treks;
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async approveTrek(trekId) {
      this.loading = true;
      try {
        await this.apiRequest("PUT", `/admin/treks/${trekId}/approve`);
        this.flash("Trek approved");
        this.fetchPendingTreks();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async rejectTrek(trekId) {
      if (!confirm("Reject this trek submission?")) return;
      this.loading = true;
      try {
        await this.apiRequest("PUT", `/admin/treks/${trekId}/reject`);
        this.flash("Trek rejected");
        this.fetchPendingTreks();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    // --- user management ---
    async fetchAllUsers() {
      this.loading = true;
      try {
        const qs = this.userRoleFilter ? `?role=${this.userRoleFilter}` : "";
        const data = await this.apiRequest("GET", `/admin/users${qs}`);
        this.allUsers = data.users;
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async blacklistUser(userId) {
      if (!confirm("Blacklist this user? They will be unable to log in or book treks.")) return;
      this.loading = true;
      try {
        await this.apiRequest("PUT", `/admin/users/${userId}/blacklist`);
        this.flash("User blacklisted");
        this.fetchAllUsers();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async activateUser(userId) {
      this.loading = true;
      try {
        await this.apiRequest("PUT", `/admin/users/${userId}/activate`);
        this.flash("User reactivated");
        this.fetchAllUsers();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    // --- staff creation ---
    validateStaffForm() {
      const f = this.staffForm;
      if (!f.name || !f.email || !f.password) {
        this.flash("Name, email and password are required", "error");
        return false;
      }
      if (f.password.length < 6) {
        this.flash("Password must be at least 6 characters", "error");
        return false;
      }
      return true;
    },

    async submitStaffForm() {
      if (!this.validateStaffForm()) return;
      this.loading = true;
      try {
        await this.apiRequest("POST", "/admin/staff", this.staffForm);
        this.flash("Staff account created");
        this.staffForm = {
          name: "", email: "", password: "", phone: "", designation: "Trek Coordinator", assigned_region: "",
        };
        this.fetchAllUsers();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    // --- all treks (admin overview) ---
    async fetchAllTreksAdmin() {
      this.loading = true;
      try {
        const qs = this.adminTrekStatusFilter ? `?status=${this.adminTrekStatusFilter}` : "";
        const data = await this.apiRequest("GET", `/admin/treks${qs}`);
        this.allTreksAdmin = data.treks;
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    // --- reports (scheduled Celery tasks, triggerable on demand) ---
    async triggerMonthlyReport() {
      this.reportResult = null;
      this.loading = true;
      try {
        const data = await this.apiRequest("POST", "/admin/reports/monthly/trigger");
        this.reportTaskId = data.task_id;
        this.flash("Monthly report generation started");
        this.pollReportTask();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async pollReportTask() {
      if (!this.reportTaskId) return;
      this.reportPolling = true;
      const poll = async () => {
        try {
          const data = await this.apiRequest("GET", `/tasks/${this.reportTaskId}`);
          if (data.state === "SUCCESS") {
            this.reportResult = data.result;
            this.reportPolling = false;
            this.flash("Monthly report generated");
          } else if (data.state === "FAILURE") {
            this.reportPolling = false;
            this.flash(`Report generation failed: ${data.error || "unknown error"}`, "error");
          } else {
            setTimeout(poll, 1500);
          }
        } catch (err) {
          this.reportPolling = false;
          this.flash(err.message, "error");
        }
      };
      poll();
    },

    async triggerReminders() {
      this.reminderResult = null;
      this.loading = true;
      try {
        const data = await this.apiRequest("POST", "/admin/reminders/trigger");
        this.reminderTaskId = data.task_id;
        this.flash("Reminder job started");
        this.pollReminderTask();
      } catch (err) {
        this.flash(err.message, "error");
      } finally {
        this.loading = false;
      }
    },

    async pollReminderTask() {
      if (!this.reminderTaskId) return;
      this.reminderPolling = true;
      const poll = async () => {
        try {
          const data = await this.apiRequest("GET", `/tasks/${this.reminderTaskId}`);
          if (data.state === "SUCCESS") {
            this.reminderResult = data.result;
            this.reminderPolling = false;
            this.flash("Reminder job completed");
          } else if (data.state === "FAILURE") {
            this.reminderPolling = false;
            this.flash(`Reminder job failed: ${data.error || "unknown error"}`, "error");
          } else {
            setTimeout(poll, 1500);
          }
        } catch (err) {
          this.reminderPolling = false;
          this.flash(err.message, "error");
        }
      };
      poll();
    },
  },
}).mount("#app");