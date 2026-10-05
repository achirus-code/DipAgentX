import DipAgentXKit
import SwiftUI

/// Fees the simulation charges on the selected broker. Prefilled with what the broker charges (Revolut X: buy 0 %,
/// sell 0.09 %; Trade Republic: 1 € per order); changing them rebooks the broker's simulated trades on the agent,
/// live trades are never touched.
struct PaperFeesSection: View {
    @Environment(AppStore.self) private var store
    let fees: PaperFees

    @State private var draft: PaperFees?
    @State private var saving = false
    @State private var error: String?

    private var current: PaperFees { draft ?? fees }
    private var changed: Bool { draft.map { $0 != fees } ?? false }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionLabel("Paper mode fees", trailing: store.showsBrokerTabs ? AnyView(BrokerName(broker: store.broker)) : nil)
            Card {
                VStack(alignment: .leading, spacing: 12) {
                    row("Buy fee", value: Binding(
                        get: { current.buy * 100 },
                        set: { draft = PaperFees(buy: max(0, min($0, 10)) / 100, sell: current.sell, fixed: current.fixed) }
                    ))
                    row("Sell fee", value: Binding(
                        get: { current.sell * 100 },
                        set: { draft = PaperFees(buy: current.buy, sell: max(0, min($0, 10)) / 100, fixed: current.fixed) }
                    ))
                    // a fixed fee per order is what Trade Republic charges – elsewhere only shown when set
                    if let fixed = current.fixed, store.broker == .tradeRepublic || fixed > 0 {
                        row("Fee per order", unit: "EUR", value: Binding(
                            get: { fixed },
                            set: { draft = PaperFees(buy: current.buy, sell: current.sell, fixed: max(0, min($0, 50))) }
                        ))
                    }
                    Group {
                        if store.broker == .tradeRepublic {
                            Text("Trade Republic charges 1 € per order (buy and sale) and no percentage. Changing a fee rebooks all simulated Trade Republic trades; live trades stay as they are.")
                        } else {
                            Text("Revolut X currently charges 0 % on buys and 0.09 % on sells. Changing a fee rebooks all simulated trades; live trades stay as they are.")
                        }
                    }
                    .font(.system(size: 10)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    if let error {
                        Text(error).font(.system(size: 10.5)).foregroundStyle(.red)
                    }
                    if changed {
                        HStack {
                            Spacer()
                            Button("Discard") { draft = nil }
                                .controlSize(.small)
                            Button {
                                save()
                            } label: {
                                if saving { ProgressView().controlSize(.mini) } else { Text("Save fees") }
                            }
                            .buttonStyle(.borderedProminent)
                            .controlSize(.small)
                            .disabled(saving)
                        }
                    }
                }
            }
        }
    }

    private func row(_ title: LocalizedStringKey, unit: String = "%", value: Binding<Double>) -> some View {
        HStack {
            Text(title).font(.system(size: 12, weight: .medium))
            Spacer()
            HStack(spacing: 4) {
                TextField("", value: value, format: .number.precision(.fractionLength(0...3)))
                    .textFieldStyle(.roundedBorder)
                    .multilineTextAlignment(.trailing)
                    .frame(width: 70)
                Text(verbatim: unit).font(.system(size: 11)).foregroundStyle(.secondary)
                    .frame(minWidth: 26, alignment: .leading)
            }
        }
    }

    private func save() {
        guard let value = draft else { return }
        saving = true
        error = nil
        Task {
            do {
                try await store.savePaperFees(value)
                draft = nil
            } catch {
                self.error = error.localizedDescription
            }
            saving = false
        }
    }
}
