import { Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { ThemeService } from './services/theme.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent {
  title = 'ui';
  // Construct ThemeService at app startup so its effect applies
  // data-theme / data-colorblind attributes to <body> before any view renders.
  readonly theme = inject(ThemeService);
}
