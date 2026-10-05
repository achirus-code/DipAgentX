import DipAgentXKit
import SwiftUI

struct TradeRepublicStatusText: View {
    let info: TradeRepublicInfo

    var body: some View {
        if info.connected {
            Text("Logged in").foregroundStyle(.green)
        } else if info.waiting {
            Text("Waiting for the confirmation").foregroundStyle(.orange)
        } else {
            Text("Not logged in")
        }
    }
}

/// The Trade Republic login: phone number + PIN → the agent asks Trade Republic → the user confirms in the Trade
/// Republic app (or enters the code of an authenticator app). A login lasts 24 hours.
struct TradeRepublicPage: View {
    @Environment(AppStore.self) private var store
    @State private var phone = ""
    @State private var pin = ""
    @State private var rememberPin = true
    @State private var code = ""
    @State private var busy = false
    @State private var error: String?
    @State private var showForm = false
    @State private var confirmingLogout = false

    private var info: TradeRepublicInfo? { store.tradeRepublic }

    var body: some View {
        Form {
            if let info {
                Section {
                    LabeledContent("Status") { TradeRepublicStatusText(info: info) }
                    if let phone = info.phoneMasked { LabeledContent("Phone number", value: phone) }
                    if let until = info.sessionExpiresAt {
                        LabeledContent("Logged in until", value: Date(ms: until).formatted(date: .abbreviated, time: .shortened))
                    }
                } footer: {
                    Text("Prices, charts and paper trading work without a login. For live trading the agent logs in to your Trade Republic account like the web app: with your phone number and PIN, confirmed in the Trade Republic app on your phone.")
                }

                if info.state == "waiting" {
                    waiting(info)
                } else if info.state == "code" {
                    codeSection
                } else if info.connected && !showForm {
                    loggedIn(info)
                } else {
                    loginForm(info)
                }

                if let marketError = info.marketError {
                    Section { Label("Market data: \(marketError)", systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange) }
                }
                Section {
                } footer: {
                    Label("Trade Republic has no official interface for programs. Its customer agreement doesn't allow access through other programs – Trade Republic may block the access or terminate the account. Use it at your own risk.", systemImage: "exclamationmark.shield.fill")
                        .foregroundStyle(.orange)
                }
            } else {
                ProgressView()
            }
        }
        .navigationTitle("Trade Republic")
        .navigationBarTitleDisplayMode(.inline)
        .animation(.snappy(duration: 0.25), value: info?.state)
        .keyboardDoneButton()
        .confirmationDialog("Logs out and forgets phone number and PIN on the agent. Live trading on Trade Republic is switched off.",
                            isPresented: $confirmingLogout, titleVisibility: .visible) {
            Button("Log out", role: .destructive) {
                Task {
                    do { try await store.logoutTradeRepublic() } catch { self.error = error.localizedDescription }
                }
            }
        }
    }

    private func loginForm(_ info: TradeRepublicInfo) -> some View {
        Group {
            Section {
                TextField("Phone number, e.g. +49 171 1234567", text: $phone)
                    .keyboardType(.phonePad)
                    .textContentType(.telephoneNumber)
                SecureField("PIN (4 digits)", text: $pin)
                    .keyboardType(.numberPad)
                Toggle("Remember PIN for the daily login", isOn: $rememberPin)
            } header: {
                Text("Log in")
            } footer: {
                Text("Trade Republic ends every login after 24 hours. With the PIN saved on the agent (file only readable by the agent), it starts the next login itself while live trading is on – you only confirm it in the Trade Republic app.")
            }
            if let message = error ?? info.error {
                Section { ErrorLabel(message: message) }
            }
            Section {
                Button {
                    Task { await login() }
                } label: {
                    HStack {
                        Spacer()
                        if busy { ProgressView().padding(.trailing, 4) }
                        Text("Log in").bold()
                        Spacer()
                    }
                }
                .disabled(busy || phone.trimmingCharacters(in: .whitespaces).count < 6 || pin.count != 4)
                if info.connected {
                    Button("Cancel") { showForm = false; error = nil }
                }
            }
        }
    }

    private func waiting(_ info: TradeRepublicInfo) -> some View {
        Section {
            HStack(spacing: 10) {
                ProgressView()
                Text(info.automatic
                     ? "The agent logs in again for the next 24 hours. Open the Trade Republic app on your phone and confirm the login."
                     : "Open the Trade Republic app on your phone and confirm the login.")
            }
            if let until = info.waitingUntil {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    let left = max(0, Int(Date(ms: until).timeIntervalSince(context.date)))
                    Text("Still \(String(left)) s").foregroundStyle(.secondary).monospacedDigit()
                }
            }
            Button("Cancel login", role: .destructive) { Task { await store.cancelTradeRepublicLogin() } }
        } header: {
            Text("Confirm in the Trade Republic app")
        }
    }

    private var codeSection: some View {
        Section {
            TextField("123456", text: $code)
                .keyboardType(.numberPad)
                .textContentType(.oneTimeCode)
                .font(.body.monospaced())
            if let error { ErrorLabel(message: error) }
            Button("Confirm") { Task { await submitCode() } }
                .disabled(busy || code.count < 4)
            Button("Cancel login", role: .destructive) { Task { await store.cancelTradeRepublicLogin() } }
        } header: {
            Text("Code from the authenticator app")
        } footer: {
            Text("Your account uses an authenticator app – enter its current code.")
        }
    }

    private func loggedIn(_ info: TradeRepublicInfo) -> some View {
        Section {
            Button("Log in again now") {
                if info.pinSaved { Task { await relogin() } } else { showForm = true }
            }
            .disabled(busy)
            Button("Log out", role: .destructive) { confirmingLogout = true }
            if let error { ErrorLabel(message: error) }
        } footer: {
            Text(info.pinSaved
                 ? "The agent starts the next login itself shortly before this one ends – as long as live trading is on or live trades are open. You only confirm it in the Trade Republic app."
                 : "The PIN is not saved: log in here again every 24 hours while the bots trade live.")
        }
    }

    private func login() async {
        guard !busy else { return }
        busy = true
        error = nil
        do {
            try await store.startTradeRepublicLogin(phone: phone, pin: pin, rememberPin: rememberPin)
            pin = ""
            showForm = false
        } catch {
            self.error = error.localizedDescription
        }
        busy = false
    }

    private func relogin() async {
        busy = true
        error = nil
        do {
            try await store.startTradeRepublicLogin(phone: nil, pin: nil, rememberPin: true)
        } catch {
            self.error = error.localizedDescription
        }
        busy = false
    }

    private func submitCode() async {
        guard !busy else { return }
        busy = true
        error = nil
        do {
            try await store.submitTradeRepublicCode(code)
            code = ""
        } catch {
            self.error = error.localizedDescription
        }
        busy = false
    }
}
