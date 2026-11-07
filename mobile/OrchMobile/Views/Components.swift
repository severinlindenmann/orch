import SwiftUI

/// Reserve the same trailing space for agent text and memo bubbles.
enum ChatBubbleLayout {
    static func agentTrailingSpace(for typeSize: DynamicTypeSize) -> CGFloat {
        typeSize.isAccessibilitySize ? 8 : 32
    }
}

struct OrbitMark: View {
    var body: some View {
        GeometryReader { proxy in
            let scale = min(proxy.size.width, proxy.size.height) / 64
            ZStack {
                Circle().stroke(Theme.text, lineWidth: 6 * scale)
                    .frame(width: 40 * scale, height: 40 * scale)
                Circle().fill(Theme.brand).frame(width: 12 * scale, height: 12 * scale)
                Circle().fill(Theme.brand)
                    .overlay(Circle().stroke(Theme.sidebar, lineWidth: 3 * scale))
                    .frame(width: 14 * scale, height: 14 * scale)
                    .offset(x: 15 * scale, y: -15 * scale)
            }
            .frame(width: proxy.size.width, height: proxy.size.height)
        }
        .accessibilityHidden(true)
    }
}

struct Brand: View {
    @Environment(\.dynamicTypeSize) private var dynamicType
    var body: some View {
        let _ = dynamicType
        HStack(spacing: 8) {
            OrbitMark().frame(width: 30, height: 30)
            Text("orch").themeFont(23, .bold).tracking(-1)
        }.accessibilityElement(children: .ignore).accessibilityLabel("orch")
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    var muted = false
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.themeFont(14, .semibold)
            .frame(maxWidth: .infinity, minHeight: 48)
            .foregroundStyle(muted || !enabled ? Theme.text.opacity(0.75) : Theme.onBrand)
            .background(muted || !enabled ? Theme.surface3 : Theme.brand, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
            .opacity(configuration.isPressed ? 0.8 : 1)
            .contentShape(Rectangle())
    }
}

/// Pressed feedback within one frame for custom-drawn rows.
struct PressStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.opacity(configuration.isPressed ? 0.7 : 1)
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.themeFont(14)
            .frame(maxWidth: .infinity, minHeight: 46)
            .foregroundStyle(Theme.text)
            .background(configuration.isPressed ? Theme.surface3 : Theme.surface2,
                        in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).stroke(Theme.borderStrong))
            .contentShape(Rectangle())
    }
}

/// Placeholder only shows after 300 ms (fast loads never flash it); the space is reserved from the start, so nothing shifts.
struct DelayedSkeleton: ViewModifier {
    let loading: Bool
    @State private var visible = false
    func body(content: Content) -> some View {
        content.redacted(reason: loading ? .placeholder : [])
            .opacity(loading ? (visible ? 0.6 : 0) : 1)
            .task(id: loading) {
                visible = false
                guard loading else { return }
                try? await Task.sleep(for: .milliseconds(300))
                visible = true
            }
    }
}

/// Full-width touch target: size and shape live inside the label, so the whole box is tappable.
struct WideButtonStyle: ButtonStyle {
    var color: Color = Theme.text
    var bordered = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.foregroundStyle(color)
            .frame(maxWidth: .infinity, minHeight: 48)
            .overlay { if bordered { RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).stroke(Theme.borderStrong) } }
            .contentShape(Rectangle())
            .opacity(configuration.isPressed ? 0.6 : 1)
    }
}

extension View {
    /// Content-shaped loading: placeholder text with the real layout until the first load finishes.
    func skeleton(_ loading: Bool) -> some View { modifier(DelayedSkeleton(loading: loading)) }
    func orchCard(border: Color = Theme.border, padding: CGFloat = 16) -> some View {
        self.padding(padding).frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).stroke(border))
    }
}

struct Eyebrow: View {
    let text: String
    var color: Color = Theme.muted
    @Environment(\.dynamicTypeSize) private var dynamicType
    var body: some View {
        let _ = dynamicType
        Text(text).themeFont(11, .semibold).tracking(1.2).foregroundStyle(color).lineLimit(2).minimumScaleFactor(0.7)
    }
}

struct ScreenHeading: View {
    let title: String
    let subtitle: String
    @Environment(\.dynamicTypeSize) private var dynamicType
    var body: some View {
        let _ = dynamicType
        VStack(alignment: .leading, spacing: 10) {
            Text(title).themeFont(29, .semibold).tracking(-1.1)
                .lineLimit(4).minimumScaleFactor(0.6)
                .accessibilityLabel(title.hasSuffix(".") ? String(title.dropLast()) : title)
                .accessibilityAddTraits(.isHeader)
            Text(subtitle).themeFont(13).foregroundStyle(Theme.muted)
        }
    }
}

/// Scrolling content never shows through the status bar / Dynamic Island area.
struct StatusBarCover: View {
    var body: some View {
        GeometryReader { proxy in
            Theme.bg.frame(height: proxy.safeAreaInsets.top).ignoresSafeArea(edges: .top)
        }.allowsHitTesting(false).accessibilityHidden(true)
    }
}

struct ModelMessage: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dynamicTypeSize) private var dynamicType
    var body: some View {
        let _ = dynamicType
        if let message = model.message {
            VStack(alignment: .leading, spacing: 6) {
                Text("⚠︎ \(message)").themeFont(13).foregroundStyle(Theme.danger)
                if let when = model.lastUpdatedText {
                    Text(when).themeFont(12).foregroundStyle(Theme.muted)
                }
                if model.phase == .ready {
                    Button { Task { await model.refresh() } } label: {
                        HStack(spacing: 8) {
                            if model.isLoading { ProgressView().tint(Theme.brand) }
                            Text(model.isLoading ? "Trying again…" : "Try again")
                        }.themeFont(13, .semibold).foregroundStyle(Theme.brand)
                            .frame(minWidth: 120, minHeight: 44, alignment: .leading).contentShape(Rectangle())
                    }.buttonStyle(PressStyle()).disabled(model.isLoading)
                }
            }.frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityElement(children: .combine)
                .transition(.opacity)
        }
    }
}

struct DayDivider: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text).themeFont(13).foregroundStyle(Theme.muted).padding(.vertical, 12).frame(maxWidth: .infinity)
    }
}

struct JumpToLatestButton: View {
    let count: Int
    var body: some View {
        VStack(spacing: 0) {
            Image(systemName: "arrow.down").themeFont(18)
            if count > 0 { Text("\(count)").themeFont(11, .semibold) }
        }.frame(minWidth: 44, minHeight: 44).foregroundStyle(Theme.brand)
            .background(Theme.surface3, in: Circle()).accessibilityLabel(count > 0 ? "Jump to latest, \(count) unread" : "Jump to latest")
            .accessibilityIdentifier("jump-latest")
    }
}

struct StatusLine: View {
    let text: String
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    init(_ text: String) { self.text = text }
    var body: some View {
        HStack(spacing: 6) {
            Text(text).themeFont(13)
            if reduceMotion { dots(phase: 0) }
            else { TimelineView(.animation(minimumInterval: 0.4)) { context in dots(phase: Int(context.date.timeIntervalSinceReferenceDate * 2.5) % 3) } }
            Spacer(minLength: 0)
        }.foregroundStyle(Theme.muted).padding(.horizontal, 16).padding(.vertical, 7).background(Theme.surface)
            .accessibilityElement(children: .ignore).accessibilityLabel(text)
    }
    private func dots(phase: Int) -> some View {
        HStack(spacing: 3) { ForEach(0..<3) { index in Circle().frame(width: 3, height: 3).opacity(reduceMotion || phase == index ? 1 : 0.3) } }.accessibilityHidden(true)
    }
}

struct PresenceDot: View {
    var body: some View { Circle().fill(Theme.brand).frame(width: 6, height: 6).accessibilityHidden(true) }
}


/// Voice note, memo and recording timer text: two-digit minutes and seconds ("00:01", "01:30").
func clockText(_ seconds: Double) -> String {
    let n = seconds.isFinite ? max(0, Int(seconds)) : 0
    return String(format: "%02d:%02d", n / 60, n % 60)
}
