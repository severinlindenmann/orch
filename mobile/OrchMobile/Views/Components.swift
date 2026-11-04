import SwiftUI

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
    var body: some View {
        HStack(spacing: 8) {
            OrbitMark().frame(width: 30, height: 30)
            Text("orch").font(Theme.font(23, .bold)).tracking(-1)
        }
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    var muted = false
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(Theme.font(14, .semibold))
            .frame(maxWidth: .infinity, minHeight: 48)
            .foregroundStyle(muted || !enabled ? Theme.muted : Theme.onBrand)
            .background(muted || !enabled ? Theme.surface3 : Theme.brand, in: RoundedRectangle(cornerRadius: 8))
            .opacity(configuration.isPressed ? 0.8 : 1)
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(Theme.font(14))
            .frame(maxWidth: .infinity, minHeight: 46)
            .foregroundStyle(Theme.text)
            .background(configuration.isPressed ? Theme.surface3 : Theme.surface2,
                        in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.border))
    }
}

extension View {
    /// Content-shaped loading: placeholder text with the real layout until the first load finishes.
    func skeleton(_ loading: Bool) -> some View {
        self.redacted(reason: loading ? .placeholder : []).opacity(loading ? 0.6 : 1)
    }
    func orchCard(border: Color = Theme.border, padding: CGFloat = 16) -> some View {
        self.padding(padding).frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(border))
    }
}

struct Eyebrow: View {
    let text: String
    var color: Color = Theme.muted
    var body: some View {
        Text(text).font(Theme.font(11, .semibold)).tracking(1.2).foregroundStyle(color)
    }
}

struct ScreenHeading: View {
    let title: String
    let subtitle: String
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(Theme.font(29, .semibold)).tracking(-1.1)
                .accessibilityAddTraits(.isHeader)
            Text(subtitle).font(Theme.font(13)).foregroundStyle(Theme.muted)
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
    var body: some View {
        if let message = model.message {
            VStack(alignment: .leading, spacing: 6) {
                Text("⚠︎ \(message)").font(Theme.font(13)).foregroundStyle(Theme.danger)
                if model.phase == .ready {
                    Button("Try again") { Task { await model.refresh() } }
                        .font(Theme.font(13, .semibold)).foregroundStyle(Theme.brand).frame(minHeight: 44)
                }
            }.frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityElement(children: .combine)
                .transition(.opacity)
        }
    }
}
