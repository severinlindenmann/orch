import SwiftUI

/// Swipe a row to the left: a short swipe reveals a "Hide" button, a long swipe hides at once, letting go early springs back.
/// The rows sit in a VStack (no List), so this does the work of `.swipeActions` with a horizontal-dominant drag that
/// keeps the row's tap and the vertical scroll working. Also a context-menu item and an accessibility action.
enum SwipeToHideRules {
    static let reveal: CGFloat = 40        // pt: past this, the button stays open
    static let buttonWidth: CGFloat = 96
    static let hideAtOnce: CGFloat = 0.55  // share of the row width
    enum Outcome: Equatable { case springBack, reveal, hide }
    /// `offset` is where the row ends up (negative = moved left).
    /// `predicted`: where the finger's speed would carry the row (DragGesture.predictedEndTranslation); a quick fling past the
    /// whole row hides too, as in Mail and Messages, even when the finger itself travelled less than `hideAtOnce`.
    static func outcome(offset: CGFloat, predicted: CGFloat? = nil, width: CGFloat) -> Outcome {
        let moved = -offset
        if width > 0, moved > width * hideAtOnce { return .hide }
        if width > 0, let predicted, moved > reveal, -predicted > width { return .hide }
        return moved > reveal ? .reveal : .springBack
    }
    /// Horizontal drags only: more sideways than up/down.
    static func isHorizontal(_ size: CGSize) -> Bool { abs(size.width) > abs(size.height) * 1.5 }
}

private struct SwipeToHide: ViewModifier {
    let id: String
    let hide: () -> Void
    @State private var offset: CGFloat = 0
    @State private var open = false
    @State private var width: CGFloat = 0
    @State private var dragging = false
    /// True from the first sideways move until shortly after the finger lifts: the row's own tap (NavigationLink) must not
    /// fire at the end of a swipe, else a swipe that hides the question also opens its chat.
    @State private var swiping = false

    func body(content: Content) -> some View {
        content
            .disabled(swiping)
            .background(Theme.surface)
            .offset(x: offset)
            .overlay { if open { Color.clear.contentShape(Rectangle()).offset(x: offset).onTapGesture { close() } } }
            .background(alignment: .trailing) {
                if offset < 0 {
                    Button { commit() } label: {
                        VStack(spacing: 4) {
                            Image(systemName: "eye.slash").themeFont(20)
                            Text("Hide").themeFont(13, .semibold)
                        }.foregroundStyle(Theme.text).frame(width: SwipeToHideRules.buttonWidth).frame(maxHeight: .infinity)
                            .background(Theme.surface3)
                    }.buttonStyle(PressStyle()).accessibilityHidden(true).accessibilityIdentifier("needs-you-hide-\(id)")
                }
            }
            .background(GeometryReader { proxy in Color.clear.onAppear { width = proxy.size.width }.onChange(of: proxy.size.width) { _, w in width = w } })
            .clipped()
            .simultaneousGesture(drag)
            .contextMenu { Button("Hide", systemImage: "eye.slash") { commit() } }
            .accessibilityAction(named: "Hide") { commit() }
    }

    private var drag: some Gesture {
        DragGesture(minimumDistance: 20)
            .onChanged { value in
                if !dragging { guard SwipeToHideRules.isHorizontal(value.translation) else { return }; dragging = true; swiping = true }
                let base: CGFloat = open ? -SwipeToHideRules.buttonWidth : 0
                offset = min(0, max(-width, base + value.translation.width))
            }
            .onEnded { value in
                guard dragging else { return }
                dragging = false
                Task { try? await Task.sleep(for: .milliseconds(350)); swiping = false }
                let base: CGFloat = open ? -SwipeToHideRules.buttonWidth : 0
                switch SwipeToHideRules.outcome(offset: base + value.translation.width, predicted: base + value.predictedEndTranslation.width, width: width) {
                case .hide: commit()
                case .reveal: withAnimation(.spring(duration: 0.25)) { offset = -SwipeToHideRules.buttonWidth; open = true }
                case .springBack: close()
                }
            }
    }

    private func close() { withAnimation(.spring(duration: 0.25)) { offset = 0; open = false } }
    private func commit() {
        withAnimation(.easeOut(duration: 0.2)) { offset = 0; open = false }
        hide()
    }
}

extension View {
    /// Trailing swipe "Hide" (plus context menu and VoiceOver action) for a row outside a List.
    func swipeToHide(id: String, hide: @escaping () -> Void) -> some View { modifier(SwipeToHide(id: id, hide: hide)) }
}
