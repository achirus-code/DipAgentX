import DipAgentXKit
import SwiftUI

/// Which brokers the agent trades on. A broker that is off is left alone (its bots stop); with only one on, the
/// tabs above the statistics disappear.
struct BrokersSection: View {
    @Environment(AppStore.self) private var store
    @State private var busy: Broker?
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionLabel("Brokers")
            Card {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(Broker.allCases) { broker in
                        HStack(spacing: 10) {
                            Image(systemName: broker.icon)
                                .font(.system(size: 14, weight: .semibold))
                                .frame(width: 22)
                                .foregroundStyle(.secondary)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(verbatim: broker.title).font(.system(size: 12, weight: .medium))
                                Text(verbatim: broker.offering).font(.system(size: 10)).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if busy == broker {
                                ProgressView().controlSize(.small)
                            } else {
                                Toggle("", isOn: binding(broker))
                                    .toggleStyle(.switch).controlSize(.small).labelsHidden()
                                    .disabled(busy != nil)
                            }
                        }
                    }
                    Text("A broker that is switched off is left alone: its bots stop, no prices, no login. With only one broker on, the tabs above the statistics disappear. A broker with open trades can't be switched off.")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    if let error {
                        Label(error, systemImage: "xmark.octagon.fill")
                            .font(.system(size: 10.5)).foregroundStyle(.red)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }

    private func binding(_ broker: Broker) -> Binding<Bool> {
        Binding(
            get: { store.enabledBrokers.contains(broker) },
            set: { on in
                busy = broker
                error = nil
                Task {
                    do { try await store.setBrokerEnabled(broker, on) } catch { self.error = error.localizedDescription }
                    busy = nil
                }
            }
        )
    }
}
