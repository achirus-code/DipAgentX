import DipAgentXKit
import SwiftUI

/// Settings section: the Trade Republic login and the entry to it.
struct TradeRepublicSection: View {
    let info: TradeRepublicInfo
    let open: (Route?) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionLabel(verbatim: "Trade Republic")
            Card {
                VStack(alignment: .leading, spacing: 10) {
                    if info.isDemo {
                        Label("Demo mode: the agent uses a simulated market (EXCHANGE=mock).", systemImage: "testtube.2")
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                    } else {
                        HStack(spacing: 8) {
                            TradeRepublicStatusBadge(info: info)
                            Spacer()
                            Button(info.connected ? LocalizedStringKey("Manage") : LocalizedStringKey("Log in")) { open(.tradeRepublicSetup) }
                                .buttonStyle(.borderedProminent)
                                .controlSize(.small)
                                .tint(info.connected ? .secondary : .accentColor)
                        }
                        if let phone = info.phoneMasked {
                            row("Phone number", phone)
                        }
                        if let until = info.sessionExpiresAt {
                            row("Logged in until", Date(ms: until).formatted(date: .abbreviated, time: .shortened))
                        }
                        if !info.connected {
                            Text("Prices and paper trading work without a login – live trading needs it.")
                                .font(.system(size: 10.5)).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        if let error = info.error {
                            Label(error, systemImage: "exclamationmark.triangle.fill")
                                .font(.system(size: 10.5)).foregroundStyle(.orange)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
        }
    }

    private func row(_ title: LocalizedStringKey, _ value: String) -> some View {
        HStack {
            Text(title).font(.system(size: 11)).foregroundStyle(.secondary)
            Spacer()
            Text(value).font(.system(size: 11, weight: .medium))
        }
    }
}

struct TradeRepublicStatusBadge: View {
    let info: TradeRepublicInfo

    var body: some View {
        Group {
            if info.connected {
                Label("Logged in", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
            } else if info.waiting {
                Label("Waiting for the confirmation", systemImage: "iphone.radiowaves.left.and.right").foregroundStyle(.orange)
            } else {
                Label("Not logged in", systemImage: "person.crop.circle.badge.questionmark").foregroundStyle(.secondary)
            }
        }
        .font(.system(size: 12, weight: .medium))
    }
}

/// The login: phone number + PIN → the agent asks Trade Republic → the user confirms in the Trade Republic app
/// (or enters the code of an authenticator app). A login lasts 24 hours.
struct TradeRepublicSetupView: View {
    @Environment(AppStore.self) private var store
    let close: () -> Void

    @State private var phone = ""
    @State private var pin = ""
    @State private var rememberPin = true
    @State private var code = ""
    @State private var busy = false
    @State private var error: String?
    @State private var showForm = false

    private var info: TradeRepublicInfo? { store.tradeRepublic }

    var body: some View {
        VStack(spacing: 0) {
            PageHeader(title: "Trade Republic", back: close)
            Divider().opacity(0.5)
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let info {
                        intro(info)
                        if info.isDemo {
                            Card {
                                Label("Demo mode: the agent uses a simulated market (EXCHANGE=mock).", systemImage: "testtube.2")
                                    .font(.system(size: 11)).foregroundStyle(.secondary)
                            }
                        } else if info.state == "waiting" {
                            waiting(info)
                        } else if info.state == "code" {
                            codeStep
                        } else if info.connected && !showForm {
                            loggedIn(info)
                        } else {
                            loginForm(info)
                        }
                        if let marketError = info.marketError {
                            Label("Market data: \(marketError)", systemImage: "exclamationmark.triangle.fill")
                                .font(.system(size: 10.5)).foregroundStyle(.orange)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    } else {
                        ProgressView().frame(maxWidth: .infinity).padding(.top, 40)
                    }
                }
                .padding(14)
            }
            .scrollIndicators(.never)
        }
        .animation(.snappy(duration: 0.25), value: info?.state)
    }

    // MARK: Sections

    private func intro(_ info: TradeRepublicInfo) -> some View {
        Card {
            VStack(alignment: .leading, spacing: 8) {
                TradeRepublicStatusBadge(info: info)
                Text("Prices, charts and paper trading work without a login. For live trading the agent logs in to your Trade Republic account like the web app: with your phone number and PIN, confirmed in the Trade Republic app on your phone.")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Label("Trade Republic has no official interface for programs. Its customer agreement doesn't allow access through other programs – Trade Republic may block the access or terminate the account. Use it at your own risk.", systemImage: "exclamationmark.shield.fill")
                    .font(.system(size: 10.5)).foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func loginForm(_ info: TradeRepublicInfo) -> some View {
        StepCard(number: 1, title: "Log in", done: false) {
            VStack(alignment: .leading, spacing: 8) {
                TextField("Phone number, e.g. +49 171 1234567", text: $phone)
                    .textFieldStyle(.roundedBorder)
                SecureField("PIN (4 digits)", text: $pin)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await login() } }
                Toggle(isOn: $rememberPin) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Remember PIN for the daily login").font(.system(size: 11.5, weight: .medium))
                        Text("Trade Republic ends every login after 24 hours. With the PIN saved on the agent (file only readable by the agent), it starts the next login itself while live trading is on – you only confirm it in the Trade Republic app.")
                            .font(.system(size: 10)).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .toggleStyle(.checkbox)
                if let message = error ?? info.error {
                    Label(message, systemImage: "xmark.octagon.fill")
                        .font(.system(size: 10.5)).foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                }
                primaryButton("Log in", icon: "person.badge.key.fill",
                              disabled: phone.trimmingCharacters(in: .whitespaces).count < 6 || pin.count != 4) {
                    await login()
                }
                if info.connected {
                    Button("Cancel") { showForm = false; error = nil }
                        .controlSize(.small)
                }
            }
        }
    }

    private func waiting(_ info: TradeRepublicInfo) -> some View {
        StepCard(number: 2, title: "Confirm in the Trade Republic app", done: false) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(info.automatic
                         ? "The agent logs in again for the next 24 hours. Open the Trade Republic app on your phone and confirm the login."
                         : "Open the Trade Republic app on your phone and confirm the login.")
                        .font(.system(size: 11))
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let until = info.waitingUntil {
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        let left = max(0, Int(Date(ms: until).timeIntervalSince(context.date)))
                        Text("Still \(String(left)) s").font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                    }
                }
                Button("Cancel login") { Task { await store.cancelTradeRepublicLogin() } }
                    .controlSize(.small)
            }
        }
    }

    private var codeStep: some View {
        StepCard(number: 2, title: "Code from the authenticator app", done: false) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Your account uses an authenticator app – enter its current code.")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                TextField("123456", text: $code)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 13, design: .monospaced))
                    .onSubmit { Task { await submitCode() } }
                if let error {
                    Label(error, systemImage: "xmark.octagon.fill").font(.system(size: 10.5)).foregroundStyle(.red)
                }
                primaryButton("Confirm", icon: "checkmark.shield.fill", disabled: code.count < 4) { await submitCode() }
                Button("Cancel login") { Task { await store.cancelTradeRepublicLogin() } }
                    .controlSize(.small)
            }
        }
    }

    private func loggedIn(_ info: TradeRepublicInfo) -> some View {
        Card {
            VStack(alignment: .leading, spacing: 10) {
                if let phone = info.phoneMasked {
                    row("Phone number", phone)
                }
                if let until = info.sessionExpiresAt {
                    row("Logged in until", Date(ms: until).formatted(date: .abbreviated, time: .shortened))
                }
                Text(info.pinSaved
                     ? "The agent starts the next login itself shortly before this one ends – as long as live trading is on or live trades are open. You only confirm it in the Trade Republic app."
                     : "The PIN is not saved: log in here again every 24 hours while the bots trade live.")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                HStack {
                    Button("Log in again now") {
                        if info.pinSaved {
                            Task { await relogin() }
                        } else {
                            showForm = true
                        }
                    }
                    .controlSize(.small)
                    .disabled(busy)
                    Spacer()
                }
                ConfirmButton(
                    title: "Log out",
                    confirmTitle: "Logs out and forgets phone number and PIN on the agent. Live trading on Trade Republic is switched off.",
                    icon: "rectangle.portrait.and.arrow.right",
                    tint: .red
                ) {
                    do { try await store.logoutTradeRepublic() } catch { self.error = error.localizedDescription }
                }
                if let error {
                    Label(error, systemImage: "xmark.octagon.fill").font(.system(size: 10.5)).foregroundStyle(.red)
                }
            }
        }
    }

    // MARK: Helpers

    private func row(_ title: LocalizedStringKey, _ value: String) -> some View {
        HStack {
            Text(title).font(.system(size: 11)).foregroundStyle(.secondary)
            Spacer()
            Text(value).font(.system(size: 11, weight: .medium))
        }
    }

    private func primaryButton(_ title: LocalizedStringKey, icon: String, disabled: Bool = false, action: @escaping () async -> Void) -> some View {
        Button {
            Task { await action() }
        } label: {
            HStack(spacing: 6) {
                if busy { ProgressView().controlSize(.small) } else { Image(systemName: icon) }
                Text(title).font(.system(size: 12, weight: .semibold))
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
            .foregroundStyle(.white)
            .background(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(LinearGradient(colors: strategyColors("dip"), startPoint: .leading, endPoint: .trailing))
            )
        }
        .buttonStyle(.plain)
        .disabled(busy || disabled)
        .opacity(disabled ? 0.5 : 1)
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
