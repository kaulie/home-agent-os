import SwiftUI
import UIKit

enum DevKeyboard {
    static func dismiss() {
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder),
            to: nil,
            from: nil,
            for: nil
        )
    }
}

private struct DevDismissKeyboardOnTapModifier: ViewModifier {
    @FocusState.Binding var isFocused: Bool
    var enabled: Bool

    func body(content: Content) -> some View {
        content
            .scrollDismissesKeyboard(.interactively)
            .simultaneousGesture(
                TapGesture().onEnded {
                    guard enabled, isFocused else { return }
                    isFocused = false
                    DevKeyboard.dismiss()
                }
            )
    }
}

private struct DevKeyboardDoneToolbarModifier: ViewModifier {
    @FocusState.Binding var isFocused: Bool

    func body(content: Content) -> some View {
        content
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("完成") {
                        isFocused = false
                        DevKeyboard.dismiss()
                    }
                    .font(.system(size: 16, weight: .semibold, design: .rounded))
                }
            }
            .onChange(of: isFocused) { focused in
                if !focused {
                    DevKeyboard.dismiss()
                }
            }
    }
}

extension View {
    func devDismissKeyboardOnTap(_ isFocused: FocusState<Bool>.Binding, enabled: Bool = true) -> some View {
        modifier(DevDismissKeyboardOnTapModifier(isFocused: isFocused, enabled: enabled))
    }

    func devKeyboardDoneToolbar(_ isFocused: FocusState<Bool>.Binding) -> some View {
        modifier(DevKeyboardDoneToolbarModifier(isFocused: isFocused))
    }
}
