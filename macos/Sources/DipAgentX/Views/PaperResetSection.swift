import DipAgentXKit
import SwiftUI

/// Paper mode: sets the selected broker's current values (result, fees, trades) back to zero.
struct PaperResetSection: View {
    @Environment(AppStore.self) private var store
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionLabel("Paper mode values", trailing: store.showsBrokerTabs ? AnyView(BrokerName(broker: store.broker)) : nil)
            Card {
                VStack(spacing: 8) {
                    Text("Sets the result, fees and trade count of this broker back to zero. Simulated trades are deleted and open paper trades discarded; live trades stay as they are.")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    ConfirmButton(
                        title: "Reset values to zero",
                        confirmTitle: "Delete all paper trades on this broker and reset its values to zero? This cannot be undone.",
                        icon: "arrow.counterclockwise",
                        tint: .orange
                    ) {
                        do { try await store.resetPaperBroker(); error = nil } catch { self.error = error.localizedDescription }
                    }
                    if let error {
                        Text(error).font(.system(size: 10.5)).foregroundStyle(.red)
                    }
                }
            }
        }
    }
}
