import SwiftUI

struct ReceiptView: View {
    let receipt: Receipt
    var time: String
    var note: String? = nil
    var onRetry: (() -> Void)? = nil
    var onDiscard: (() -> Void)? = nil
    /// Sits at the bottom-right inside the bubble next to the text (no own full-width line).
    var inline = false
    var tint: Color = Theme.muted
    /// "Waiting" beside the clock while no offline banner says why the message has not left yet.
    var waitingWord = false
    static func showsWaitingWord(offline: Bool, note: String?) -> Bool { !offline && note == nil }
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .trailing, spacing: 6) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 6) { stamp; recovery }
                VStack(alignment: .trailing, spacing: 0) { stamp; recovery }
            }
            if case .queued = receipt, let note {
                Text(note).foregroundStyle(tint).accessibilityIdentifier("receipt-wait")
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .themeFont(inline ? 12 : 13).foregroundStyle(tint)
        .frame(maxWidth: inline ? nil : .infinity, alignment: .trailing)
    }

    private var stamp: some View {
        HStack(spacing: 5) {
            Text(time)
            Group {
                switch receipt {
                case .queued:
                    if waitingWord { Text("Waiting").accessibilityHidden(true) }
                    Image(systemName: "clock").accessibilityLabel("Waiting to send").accessibilityIdentifier("receipt-queued")
                case .sent:
                    Image(systemName: "checkmark").accessibilityLabel("Sent").accessibilityIdentifier("receipt-sent")
                case .delivered:
                    checks.accessibilityLabel("Delivered").accessibilityIdentifier("receipt-delivered")
                case .started:
                    checks
                        .foregroundStyle(Theme.brand).accessibilityElement(children: .ignore)
                        .accessibilityLabel("Delivered").accessibilityIdentifier("receipt-started")
                case .failed(let message):
                    Text("Not sent").foregroundStyle(Theme.danger).accessibilityHint(message)
                        .accessibilityIdentifier("receipt-failed")
                }
            }.id(receiptKey).transition(reduceMotion ? .identity : .opacity.combined(with: .offset(y: 3)))
        }.animation(reduceMotion ? nil : .easeOut(duration: 0.3), value: receipt)
    }

    private var checks: some View {
        HStack(spacing: 0) {
            Image(systemName: "checkmark")
            Image(systemName: "checkmark").offset(x: -5).padding(.trailing, -5)
        }.accessibilityElement(children: .ignore)
    }

    private var receiptKey: String {
        switch receipt { case .queued: "queued"; case .sent: "sent"; case .delivered: "delivered"
        case .started: "started"; case .failed: "failed" }
    }

    @ViewBuilder private var recovery: some View {
        if case .failed = receipt {
            HStack(spacing: 8) {
                Button { onRetry?() } label: {
                    Text("Retry").frame(minWidth: 44, minHeight: 44).contentShape(Rectangle())
                }.disabled(onRetry == nil).accessibilityIdentifier("receipt-retry")
                Button { onDiscard?() } label: {
                    Text("Discard").frame(minWidth: 44, minHeight: 44).contentShape(Rectangle())
                }.disabled(onDiscard == nil).accessibilityIdentifier("receipt-discard")
            }.foregroundStyle(Theme.brand).buttonStyle(PressStyle())
        }
    }
}
