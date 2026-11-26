import SwiftUI

/// Swipe a row to the left: a short swipe reveals a "Hide" button, a long swipe hides at once, letting go early springs back.
/// The rows sit in a VStack (no List), so this does the work of `.swipeActions` with a horizontal-dominant drag that
/// keeps the row's tap and the vertical scroll working. Also a context-menu item and an accessibility action.
/// Reduce Motion: the row still follows the finger, but reveal, spring back, close and hide jump instead of animating.
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
    /// Chat rows have no full swipe: a long swipe or a fling only shows the buttons, it never archives or deletes.
    static func actionsOutcome(offset: CGFloat, predicted: CGFloat? = nil, width: CGFloat) -> Outcome {
        outcome(offset: offset, predicted: predicted, width: width) == .springBack ? .springBack : .reveal
    }
    /// Horizontal drags only: more sideways than up/down.
    static func isHorizontal(_ size: CGSize) -> Bool { abs(size.width) > abs(size.height) * 1.5 }

    /// The moves a row makes on its own once the finger lifts: `spring` = reveal, spring back, close; `commit` = Hide or a
    /// button runs. The drag itself always follows the finger, unanimated.
    enum Settle { case spring, commit }
    /// With Reduce Motion on there is no settle motion: the row jumps to where it ends (as ChatScreens scrolls without
    /// animation). Read on every move, so changing the setting while the app is open takes effect on the next swipe.
    static func settle(_ kind: Settle, reduceMotion: Bool) -> Transaction {
        guard !reduceMotion else { var none = Transaction(); none.disablesAnimations = true; return none }
        switch kind {
        case .spring: return Transaction(animation: .spring(duration: 0.25))
        case .commit: return Transaction(animation: .easeOut(duration: 0.2))
        }
    }
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
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

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
                case .reveal: withTransaction(SwipeToHideRules.settle(.spring, reduceMotion: reduceMotion)) { offset = -SwipeToHideRules.buttonWidth; open = true }
                case .springBack: close()
                }
            }
    }

    private func close() { withTransaction(SwipeToHideRules.settle(.spring, reduceMotion: reduceMotion)) { offset = 0; open = false } }
    private func commit() {
        withTransaction(SwipeToHideRules.settle(.commit, reduceMotion: reduceMotion)) { offset = 0; open = false }
        hide()
    }
}

extension View {
    /// Trailing swipe "Hide" (plus context menu and VoiceOver action) for a row outside a List.
    func swipeToHide(id: String, hide: @escaping () -> Void) -> some View { modifier(SwipeToHide(id: id, hide: hide)) }
}

/// One button behind a row that is swiped left (outside a List): Archive, Delete.
struct SwipeRowAction: Identifiable {
    let title: String
    let symbol: String
    var role: ButtonRole? = nil
    let run: () -> Void
    var id: String { title }
}

/// `.swipeActions` for rows in a VStack (Chats is a ScrollView, not a List): a swipe shows the buttons, a tap on one runs it
/// (no full swipe, so a fling never archives a chat by mistake). Also a context menu and VoiceOver actions.
private struct SwipeRowActions: ViewModifier {
    let actions: [SwipeRowAction]
    @State private var offset: CGFloat = 0
    @State private var open = false
    @State private var width: CGFloat = 0
    @State private var dragging = false
    @State private var swiping = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private var buttonsWidth: CGFloat { SwipeToHideRules.buttonWidth * CGFloat(actions.count) }

    func body(content: Content) -> some View {
        let base = content
            .disabled(swiping)
            .background(Theme.surface)
            .offset(x: offset)
            .overlay { if open { Color.clear.contentShape(Rectangle()).offset(x: offset).onTapGesture { close() } } }
            .background(alignment: .trailing) {
                if offset < 0 {
                    HStack(spacing: 0) {
                        // The first action sits outermost (right edge), like List swipe actions.
                        ForEach(actions.reversed()) { action in
                            Button { run(action) } label: {
                                VStack(spacing: 4) {
                                    Image(systemName: action.symbol).themeFont(20)
                                    Text(action.title).themeFont(13, .semibold)
                                }.foregroundStyle(action.role == .destructive ? Color.white : Theme.onBrand)
                                    .frame(width: SwipeToHideRules.buttonWidth).frame(maxHeight: .infinity)
                                    .background(action.role == .destructive ? Theme.danger : Theme.brand)
                            }.buttonStyle(PressStyle()).accessibilityLabel(action.title)
                        }
                    }
                }
            }
            .background(GeometryReader { proxy in Color.clear.onAppear { width = proxy.size.width }.onChange(of: proxy.size.width) { _, w in width = w } })
            .clipped()
            .simultaneousGesture(drag)
            .contextMenu {
                ForEach(actions) { action in Button(role: action.role) { run(action) } label: { Label(action.title, systemImage: action.symbol) } }
            }
        return actions.reduce(AnyView(base)) { view, action in AnyView(view.accessibilityAction(named: action.title) { run(action) }) }
    }

    private var drag: some Gesture {
        DragGesture(minimumDistance: 20)
            .onChanged { value in
                if !dragging { guard SwipeToHideRules.isHorizontal(value.translation) else { return }; dragging = true; swiping = true }
                let start: CGFloat = open ? -buttonsWidth : 0
                offset = min(0, max(-width, start + value.translation.width))
            }
            .onEnded { value in
                guard dragging else { return }
                dragging = false
                Task { try? await Task.sleep(for: .milliseconds(350)); swiping = false }
                let start: CGFloat = open ? -buttonsWidth : 0
                // No full swipe: a chat is archived or deleted only by a tap on its button, never by a fling.
                switch SwipeToHideRules.actionsOutcome(offset: start + value.translation.width, predicted: start + value.predictedEndTranslation.width, width: width) {
                case .hide, .reveal: withTransaction(SwipeToHideRules.settle(.spring, reduceMotion: reduceMotion)) { offset = -buttonsWidth; open = true }
                case .springBack: close()
                }
            }
    }

    private func close() { withTransaction(SwipeToHideRules.settle(.spring, reduceMotion: reduceMotion)) { offset = 0; open = false } }
    private func run(_ action: SwipeRowAction) {
        withTransaction(SwipeToHideRules.settle(.commit, reduceMotion: reduceMotion)) { offset = 0; open = false }
        action.run()
    }
}

extension View {
    /// Trailing swipe buttons (plus context menu and VoiceOver actions) for a row outside a List; empty = none.
    @ViewBuilder func swipeRowActions(_ actions: [SwipeRowAction]) -> some View {
        if actions.isEmpty { self } else { modifier(SwipeRowActions(actions: actions)) }
    }
}
